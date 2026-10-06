from __future__ import annotations

import os
import smtplib
from datetime import date, datetime, timedelta
from decimal import Decimal
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from model.models import (
    Candidate,
    OfferStatus,
    OfferTemplate,
    OfferTracking,
    User,
)

EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASS = os.getenv("EMAIL_PASS", "")



VALID_TRANSITIONS: dict[str, list[str]] = {
    OfferStatus.draft:    [OfferStatus.pending_approval if hasattr(OfferStatus, "pending_approval") else "pending_approval", "approved", "withdrawn"],
    "pending_approval":   ["approved", "withdrawn"],
    "approved":           [OfferStatus.sent, "withdrawn"],
    OfferStatus.sent:     [OfferStatus.accepted, OfferStatus.rejected, OfferStatus.expired, "withdrawn"],
    OfferStatus.accepted: [],
    OfferStatus.rejected: [],
    OfferStatus.expired:  [],
    "withdrawn":          [],
}


ACTION_STATUS_MAP = {
    "submit":   "pending_approval",
    "approve":  "approved",
    "send":     OfferStatus.sent,
    "accept":   OfferStatus.accepted,
    "decline":  OfferStatus.rejected,
    "expire":   OfferStatus.expired,
    "withdraw": "withdrawn",
}



def _get_offer(db: Session, offer_id: int) -> OfferTracking:
    offer = db.query(OfferTracking).filter(OfferTracking.id == offer_id).first()
    if not offer:
        raise HTTPException(404, "Offer not found")
    return offer


def _salary_breakdown(offer: OfferTracking) -> Optional[dict]:
    
    cols = ("basic", "hra", "conveyance", "special_allowance",
            "performance_bonus", "stipend")
    row = {c: getattr(offer, c, None) for c in cols}
    if any(v is not None for v in row.values()):
        row["gross_total"] = offer.salary_offered
        return row

    
    breakdown: dict = {}
    for item in (offer.benefits or []):
        if ":" in item:
            key, _, val = item.partition(":")
            try:
                breakdown[key.strip().lower().replace(" ", "_")] = Decimal(val.strip().replace(",", ""))
            except Exception:
                pass
    if breakdown:
        breakdown["gross_total"] = offer.salary_offered
        return breakdown
    return None


def _timeline(offer: OfferTracking) -> List[dict]:
   
    events = []
    if offer.created_at:
        events.append({
            "event":     "Offer Created",
            "actor":     "HR Admin",
            "actor_role": "HR",
            "timestamp": offer.created_at,
        })
    status_val = offer.status.value if hasattr(offer.status, "value") else str(offer.status)
    if status_val in ("approved", "Approved"):
        events.append({
            "event":     "HR Approval",
            "actor":     "HR Head",
            "actor_role": "HR Head",
            "timestamp": offer.updated_at,
        })
    if offer.sent_date:
        events.append({
            "event":     "Sent to Candidate",
            "actor":     "System",
            "actor_role": "System",
            "timestamp": offer.sent_date,
        })
    if offer.response_date:
        status_val = offer.status.value if hasattr(offer.status, "value") else str(offer.status)
        evt = "Accepted by Candidate" if "accept" in status_val.lower() else "Declined by Candidate"
        events.append({
            "event":     evt,
            "actor":     "Candidate",
            "actor_role": "Candidate",
            "timestamp": offer.response_date,
        })
    return events


def _map_offer(offer: OfferTracking) -> dict:
    
    status_val = offer.status.value if hasattr(offer.status, "value") else str(offer.status)
    return {
        "id":                offer.id,
        "candidate_id":      offer.candidate_id,
        "candidate_name":    offer.candidate_name,
        "candidate_email":   offer.candidate_email,
        "candidate_phone":   getattr(offer, "candidate_phone", None),
        "candidate_source":  getattr(offer, "candidate_source", None),
        "position":          offer.position,
        "department":        offer.department,
        "employment_type":   getattr(offer, "employment_type", None),
        "join_date":         getattr(offer, "join_date", None),
        "grade":             getattr(offer, "grade", None),
        "experience_required": getattr(offer, "experience_required", None),
        "gross_salary":      offer.salary_offered,
        "salary_breakdown":  _salary_breakdown(offer),
        "status":            status_val,
        "timeline":          _timeline(offer),
        "expiry_date":       offer.expiry_date,
        "sent_date":         offer.sent_date,
        "response_date":     offer.response_date,
        "offer_content":     offer.offer_content,
        "notes":             offer.notes,
        "created_by":        offer.created_by,
        "created_at":        offer.created_at,
        "updated_at":        offer.updated_at,
    }


def _status_val(offer: OfferTracking) -> str:
    return offer.status.value if hasattr(offer.status, "value") else str(offer.status)




def get_offer_kpi(db: Session) -> dict:
    
    offers = db.query(OfferTracking).all()

    counts: dict[str, int] = {
        "total_offers": len(offers),
        "draft": 0, "pending_approval": 0, "approved": 0,
        "sent": 0, "accepted": 0, "declined": 0,
        "expired": 0, "withdrawn": 0,
    }

    for o in offers:
        s = _status_val(o).lower().replace(" ", "_").replace("-", "_")
        for key in counts:
            if key != "total_offers" and s == key:
                counts[key] += 1
                break
            
            if key == "declined" and s in ("rejected", "declined"):
                counts["declined"] += 1
                break

    return counts


def get_tab_counts(db: Session) -> dict:
    return get_offer_kpi(db)



def list_offers(
    db:          Session,
    user:        User,
    search:      Optional[str] = None,
    status:      Optional[str] = None,
    department:  Optional[str] = None,
    offer_type:  Optional[str] = None,
    skip:        int = 0,
    limit:       int = 20,
) -> List[dict]:
    
    query = db.query(OfferTracking)

    
    if user.role.lower() != "admin":
        query = query.filter(OfferTracking.created_by == user.id)

    if search:
        sl = f"%{search}%"
        query = query.filter(
            OfferTracking.candidate_name.ilike(sl)
            | OfferTracking.candidate_email.ilike(sl)
            | OfferTracking.position.ilike(sl)
        )

    if status and status not in ("All Status", "all", ""):
        
        db_status = "rejected" if status.lower() == "declined" else status.lower()
        query = query.filter(func.lower(OfferTracking.status) == db_status)

    if department and department not in ("All Departments", "all", ""):
        query = query.filter(OfferTracking.department == department)

    if offer_type and offer_type not in ("All Offer Types", "all", ""):
        if hasattr(OfferTracking, "employment_type"):
            query = query.filter(OfferTracking.employment_type == offer_type)

    offers = query.order_by(OfferTracking.created_at.desc()).offset(skip).limit(limit).all()
    return [_map_offer(o) for o in offers]


def get_offer_detail(db: Session, offer_id: int, user: User) -> dict:
    offer = _get_offer(db, offer_id)
    if user.role.lower() != "admin" and offer.created_by != user.id:
        raise HTTPException(403, "Access forbidden")
    return _map_offer(offer)



def create_offer(db: Session, payload, user: User) -> dict:
    
    
    gross = payload.gross_salary
    if gross is None:
        components = [
            payload.basic, payload.hra, payload.conveyance,
            payload.special_allowance, payload.performance_bonus, payload.stipend,
        ]
        total = sum(c for c in components if c)
        gross = total if total else None

    
    benefits = []
    comp_map = {
        "Basic": payload.basic,
        "HRA": payload.hra,
        "Conveyance": payload.conveyance,
        "Special Allowance": payload.special_allowance,
        "Performance Bonus": payload.performance_bonus,
        "Stipend": payload.stipend,
    }
    for label, val in comp_map.items():
        if val:
            benefits.append(f"{label}: {int(val)}")

    offer = OfferTracking(
        candidate_id    = payload.candidate_id,
        candidate_name  = payload.candidate_name,
        candidate_email = payload.candidate_email,
        position        = payload.position,
        department      = payload.department,
        salary_offered  = float(gross) if gross else None,
        benefits        = benefits,
        offer_content   = payload.offer_content,
        status          = OfferStatus.draft,
        expiry_date     = payload.expiry_date,
        notes           = payload.notes,
        template_id     = payload.template_id,
        created_by      = user.id,
        created_at      = datetime.utcnow(),
        updated_at      = datetime.utcnow(),
    )

    
    for col in ("candidate_phone", "candidate_source", "employment_type",
                "join_date", "grade", "experience_required"):
        if hasattr(offer, col) and hasattr(payload, col):
            setattr(offer, col, getattr(payload, col))

    db.add(offer)
    db.commit()
    db.refresh(offer)
    return _map_offer(offer)




def update_offer(db: Session, offer_id: int, payload, user: User) -> dict:
    offer = _get_offer(db, offer_id)
    if user.role.lower() != "admin" and offer.created_by != user.id:
        raise HTTPException(403, "Access forbidden")

    for key, value in payload.model_dump(exclude_unset=True).items():
        if key in ("basic", "hra", "conveyance", "special_allowance",
                   "performance_bonus", "stipend"):
            # Repack benefits
            continue
        if hasattr(offer, key):
            setattr(offer, key, value)

    
    comp_payload = {k: getattr(payload, k, None) for k in
                    ("basic", "hra", "conveyance", "special_allowance",
                     "performance_bonus", "stipend")}
    new_comps = {k: v for k, v in comp_payload.items() if v is not None}
    if new_comps:
        gross = sum(new_comps.values())
        offer.salary_offered = float(gross)
        existing = {item.split(":")[0].strip(): item for item in (offer.benefits or [])}
        label_map = {
            "basic": "Basic", "hra": "HRA", "conveyance": "Conveyance",
            "special_allowance": "Special Allowance",
            "performance_bonus": "Performance Bonus", "stipend": "Stipend",
        }
        for k, v in new_comps.items():
            label = label_map[k]
            existing[label] = f"{label}: {int(v)}"
        offer.benefits = list(existing.values())

    offer.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(offer)
    return _map_offer(offer)



def process_status_action(
    db:       Session,
    offer_id: int,
    payload,
    user:     User,
) -> dict:
    
    offer  = _get_offer(db, offer_id)
    action = payload.action.lower()

    new_status = ACTION_STATUS_MAP.get(action)
    if not new_status:
        raise HTTPException(400, f"Unknown action '{action}'. Valid: {list(ACTION_STATUS_MAP)}")

    
    try:
        offer.status = OfferStatus(new_status)
    except ValueError:
        offer.status = new_status  

    
    now = datetime.utcnow()
    if action == "send" and not offer.sent_date:
        offer.sent_date = now
        
        if not offer.expiry_date:
            offer.expiry_date = (now + timedelta(days=30)).date()
    if action in ("accept", "decline") and not offer.response_date:
        offer.response_date = now

    offer.updated_at = now

    
    if action in ("send", "accept", "decline"):
        try:
            from routers.Candidate_assessments.Assessment.utils.stage_sync import (
                update_candidate_stage_all_tables,
            )
            stage_map = {"send": "Offered", "accept": "Offer Accepted", "decline": "Offer Declined"}
            update_candidate_stage_all_tables(db, offer.candidate_email, stage_map[action])
        except Exception:
            pass

    db.commit()
    db.refresh(offer)

    # Offer accepted -> start onboarding (invite record + email).
    if action == "accept":
        from services.offer_onboarding import start_onboarding_for_accepted_offer
        start_onboarding_for_accepted_offer(db, offer)
        db.refresh(offer)
    return _map_offer(offer)




def send_offer_email(db: Session, payload, user: User) -> dict:
    offer = _get_offer(db, payload.offer_id)
    if user.role.lower() != "admin" and offer.created_by != user.id:
        raise HTTPException(403, "Access forbidden")

    recipient = payload.recipient_email or offer.candidate_email
    subject   = payload.subject or f"Job Offer — {offer.position}"

    breakdown = _salary_breakdown(offer) or {}
    comp_rows = ""
    label_map = {
        "basic": "Basic", "hra": "HRA", "conveyance": "Conveyance",
        "special_allowance": "Special Allowance",
        "performance_bonus": "Performance Bonus", "stipend": "Stipend",
    }
    for key, label in label_map.items():
        val = breakdown.get(key)
        if val:
            comp_rows += f"<tr><td>{label}</td><td style='text-align:right'>₹{int(val):,}</td></tr>"

    extra = payload.extra_message or ""
    join_str = str(getattr(offer, "join_date", "")) or ""

    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333">
    <div style="max-width:620px;margin:auto;padding:20px">
      <div style="background:#1a56db;color:white;padding:24px;border-radius:8px 8px 0 0;text-align:center">
        <h2 style="margin:0">🎉 Congratulations! You have a Job Offer</h2>
      </div>
      <div style="background:#fff;padding:28px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 8px 8px">
        <p>Dear <strong>{offer.candidate_name}</strong>,</p>
        <p>{offer.offer_content.replace(chr(10), '<br>')}</p>
        {f'<p>{extra}</p>' if extra else ''}
        <table style="width:100%;border-collapse:collapse;margin:16px 0">
          <tr style="background:#f3f4f6">
            <td style="padding:8px"><strong>Position</strong></td>
            <td style="padding:8px">{offer.position}</td>
          </tr>
          <tr>
            <td style="padding:8px"><strong>Department</strong></td>
            <td style="padding:8px">{offer.department or ''}</td>
          </tr>
          {f'<tr style="background:#f3f4f6"><td style="padding:8px"><strong>Joining Date</strong></td><td style="padding:8px">{join_str}</td></tr>' if join_str else ''}
          <tr {'style="background:#f3f4f6"' if not join_str else ''}>
            <td style="padding:8px"><strong>Total CTC</strong></td>
            <td style="padding:8px;font-size:18px;color:#1a56db">
              ₹{int(offer.salary_offered):,} / year
            </td>
          </tr>
        </table>
        {f'<h4>Compensation Breakup</h4><table style="width:100%;border-collapse:collapse">{comp_rows}</table>' if comp_rows else ''}
        <p style="margin-top:24px">We look forward to welcoming you to our team!</p>
        <p>Warm regards,<br><strong>Recruitment Team</strong></p>
      </div>
    </div>
    </body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_USER
    msg["To"]      = recipient
    msg.attach(MIMEText(offer.offer_content, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise HTTPException(500, "Email authentication failed — check EMAIL_USER / EMAIL_PASS env vars")
    except smtplib.SMTPException as exc:
        raise HTTPException(500, f"SMTP error: {exc}")

    
    offer.status    = OfferStatus.sent
    offer.sent_date = offer.sent_date or datetime.utcnow()
    if not offer.expiry_date:
        offer.expiry_date = (datetime.utcnow() + timedelta(days=payload.expiry_days)).date()
    offer.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(offer)

    return {
        "success":    True,
        "offer_id":   offer.id,
        "sent_to":    recipient,
        "status":     _status_val(offer),
    }




def duplicate_offer(db: Session, offer_id: int, user: User) -> dict:
    original = _get_offer(db, offer_id)
    copy = OfferTracking(
        candidate_id    = original.candidate_id,
        candidate_name  = original.candidate_name,
        candidate_email = original.candidate_email,
        position        = original.position,
        department      = original.department,
        salary_offered  = original.salary_offered,
        benefits        = list(original.benefits or []),
        offer_content   = original.offer_content,
        status          = OfferStatus.draft,
        expiry_date     = original.expiry_date,
        notes           = original.notes,
        template_id     = original.template_id,
        created_by      = user.id,
        created_at      = datetime.utcnow(),
        updated_at      = datetime.utcnow(),
    )
    db.add(copy)
    db.commit()
    db.refresh(copy)
    return _map_offer(copy)



def bulk_action(db: Session, payload, user: User) -> dict:
    success, failed = [], []
    for oid in payload.offer_ids:
        try:
            offer = _get_offer(db, oid)
            if user.role.lower() != "admin" and offer.created_by != user.id:
                failed.append({"id": oid, "reason": "Forbidden"})
                continue

            action = payload.action.lower()
            if action == "delete":
                db.delete(offer)
            else:
                new_status = ACTION_STATUS_MAP.get(action)
                if new_status:
                    try:
                        offer.status = OfferStatus(new_status)
                    except ValueError:
                        offer.status = new_status  # type: ignore
                    if action == "send" and not offer.sent_date:
                        offer.sent_date = datetime.utcnow()
                    if action in ("accept", "decline") and not offer.response_date:
                        offer.response_date = datetime.utcnow()
                    offer.updated_at = datetime.utcnow()
            success.append(oid)
        except HTTPException as exc:
            failed.append({"id": oid, "reason": exc.detail})
        except Exception as exc:
            failed.append({"id": oid, "reason": str(exc)})

    db.commit()

    # Offers accepted in bulk also start onboarding.
    if payload.action.lower() == "accept":
        from services.offer_onboarding import start_onboarding_for_accepted_offer
        for oid in success:
            accepted = db.query(OfferTracking).filter(OfferTracking.id == oid).first()
            if accepted is not None:
                start_onboarding_for_accepted_offer(db, accepted)

    return {
        "action":  payload.action,
        "total":   len(payload.offer_ids),
        "success": len(success),
        "failed":  failed,
    }



def delete_offer(db: Session, offer_id: int, user: User) -> dict:
    offer = _get_offer(db, offer_id)
    if user.role.lower() != "admin" and offer.created_by != user.id:
        raise HTTPException(403, "Access forbidden")
    db.delete(offer)
    db.commit()
    return {"message": "Offer deleted", "offer_id": offer_id}




def get_offer_analytics(db: Session) -> dict:
    offers = db.query(OfferTracking).all()
    now    = datetime.utcnow()
    total  = len(offers)
    if total == 0:
        return {
            "acceptance_rate_pct": 0.0,
            "acceptance_summary": "0 accepted out of 0 offers",
            "avg_time_to_accept_days": 0.0,
            "avg_time_label": "From offer sent to acceptance",
            "top_department": "—",
            "top_department_label": "Most offers extended",
            "monthly_trend_pct": 0.0,
            "monthly_trend_label": "vs previous month",
            "type_distribution": [],
            "department_stats": [],
            "status_distribution": [],
        }

    accepted = [o for o in offers if "accept" in _status_val(o).lower()]
    acc_rate = round(len(accepted) / total * 100, 1)
    acc_summary = f"{len(accepted)} accepted out of {total} offers"

    
    times = []
    for o in accepted:
        if o.sent_date and o.response_date:
            times.append((o.response_date - o.sent_date).days)
    avg_time = round(sum(times) / len(times), 1) if times else 0.0

    
    dept_counts: dict[str, int] = {}
    for o in offers:
        d = o.department or "Unknown"
        dept_counts[d] = dept_counts.get(d, 0) + 1
    top_dept = max(dept_counts, key=dept_counts.get) if dept_counts else "—"

    
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_start = (this_month_start - timedelta(days=1)).replace(day=1)
    this_month = sum(1 for o in offers if o.created_at >= this_month_start)
    last_month = sum(1 for o in offers if last_month_start <= o.created_at < this_month_start)
    trend = round((this_month - last_month) / max(last_month, 1) * 100, 1)

    
    type_counts: dict[str, int] = {}
    for o in offers:
        t = getattr(o, "employment_type", None) or "Full-time"
        type_counts[t] = type_counts.get(t, 0) + 1
    type_dist = [
        {"type": k, "count": v, "pct_of_total": round(v / total * 100, 1)}
        for k, v in sorted(type_counts.items(), key=lambda x: -x[1])
    ]

    
    dept_stats = [
        {"department": k, "count": v, "pct_of_total": round(v / total * 100, 1)}
        for k, v in sorted(dept_counts.items(), key=lambda x: -x[1])
    ]

    
    status_counts: dict[str, int] = {}
    for o in offers:
        s = _status_val(o)
        status_counts[s] = status_counts.get(s, 0) + 1
    status_dist = [{"status": k, "count": v} for k, v in status_counts.items()]

    return {
        "acceptance_rate_pct":     acc_rate,
        "acceptance_summary":      acc_summary,
        "avg_time_to_accept_days": avg_time,
        "avg_time_label":          "From offer sent to acceptance",
        "top_department":          top_dept,
        "top_department_label":    "Most offers extended",
        "monthly_trend_pct":       trend,
        "monthly_trend_label":     "vs previous month",
        "type_distribution":       type_dist,
        "department_stats":        dept_stats,
        "status_distribution":     status_dist,
    }




def export_offers(db: Session, user: User) -> List[dict]:
    offers = db.query(OfferTracking).all()
    return [
        {
            "ID":               o.id,
            "Candidate":        o.candidate_name,
            "Email":            o.candidate_email,
            "Position":         o.position,
            "Department":       o.department or "",
            "Gross CTC":        o.salary_offered or "",
            "Status":           _status_val(o),
            "Sent Date":        str(o.sent_date.date()) if o.sent_date else "",
            "Response Date":    str(o.response_date.date()) if o.response_date else "",
            "Expiry Date":      str(o.expiry_date) if o.expiry_date else "",
        }
        for o in offers
        if user.role.lower() == "admin" or o.created_by == user.id
    ]