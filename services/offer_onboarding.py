"""
Offer accepted -> onboarding started.

When an offer becomes "Accepted", create the candidate's onboarding record
(the same record HR creates by hand with "Invite") and email them the link to
fill the onboarding form. The step is idempotent and never raises, so a mail
or database problem can never undo or block the offer acceptance itself.
"""
import asyncio
import logging
import threading

from sqlalchemy import func
from sqlalchemy.orm import Session

from model.onboarding.candidate import Candidate as OnboardingCandidate

log = logging.getLogger(__name__)


def is_accepted(offer) -> bool:
    status = getattr(offer.status, "value", offer.status)
    return str(status).strip().lower() == "accepted"


def _run_coroutine(coro) -> None:
    """Run an async mail call from sync code, whether or not a loop is running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)      # normal case: FastAPI threadpool, no loop here
        return
    # A loop is already running in this thread: use a helper thread.
    err: list = []

    def _worker():
        try:
            asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            err.append(exc)

    t = threading.Thread(target=_worker)
    t.start()
    t.join()
    if err:
        raise err[0]


def start_onboarding_for_accepted_offer(db: Session, offer) -> dict:
    """Create the onboarding invite for an accepted offer. Returns a result dict."""
    try:
        if not is_accepted(offer):
            return {"started": False, "reason": "offer is not accepted"}

        email = (offer.candidate_email or "").strip()
        if not email:
            return {"started": False, "reason": "offer has no candidate email"}

        # Idempotent: one live onboarding record per email.
        existing = (
            db.query(OnboardingCandidate)
            .filter(func.lower(OnboardingCandidate.email) == email.lower())
            .filter(OnboardingCandidate.status != "REJECTED")
            .first()
        )
        if existing:
            return {
                "started": False,
                "reason": "onboarding already exists",
                "onboarding_id": existing.id,
            }

        # Imported lazily to avoid a circular import with the router module.
        from routers.onboarding.admin_candidates import (
            _send_invite_email,
            build_onboarding_link,
            create_onboarding_invite,
        )

        record = create_onboarding_invite(
            db,
            full_name=offer.candidate_name,
            email=email,
            mobile=None,
            verification_options=[],
        )

        email_sent = False
        try:
            _run_coroutine(
                _send_invite_email(
                    email=email,
                    name=offer.candidate_name,
                    link=build_onboarding_link(record.invite_token),
                    expiry=record.token_expires_at,
                )
            )
            email_sent = True
        except Exception as exc:  # noqa: BLE001
            log.warning("Onboarding invite email failed for %s: %s", email, exc)

        return {
            "started": True,
            "onboarding_id": record.id,
            "email_sent": email_sent,
        }
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.exception("Could not start onboarding for offer %s", getattr(offer, "id", "?"))
        return {"started": False, "reason": f"error: {exc}"}
