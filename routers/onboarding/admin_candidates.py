print("admin_candidates router loaded")

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import or_
import os
from uuid import uuid4
from datetime import datetime, timedelta

from fastapi_mail import FastMail, MessageSchema, MessageType

from core.database import get_db
from core.mail import mail_config
from model.onboarding.candidate import Candidate
from schema.onboarding.candidate import (
    CandidateCreate,
    CandidateUpdate,
    CandidateOut,
    PaginatedCandidates,
    compute_credits,
)

router = APIRouter(
    prefix="/api/onboarding-forms/candidates",
    tags=["Onboarding Forms"],
)




async def _send_invite_email(email: str, name: str, link: str, expiry: datetime):
    
    html_body = f"""
    <div style="font-family:Arial,sans-serif;line-height:1.6;color:#333;">
        <p>Hello <b>{name}</b>,</p>
        <p>Welcome to <b>Levitica Technologies Private Limited</b>.</p>
        <p>We have initiated your onboarding process.</p>
        <p>Click the button below to complete your onboarding form:</p>
        <p>
            <a href="{link}"
               style="background:#2563eb;color:#fff;padding:10px 18px;
                      text-decoration:none;border-radius:6px;display:inline-block;">
               Complete Onboarding
            </a>
        </p>
        <p style="margin-top:12px;">
            <b>Note:</b> This link is valid till
            <b>{expiry.strftime("%d-%b-%Y")}</b>.
        </p>
        <br/>
        <p>
            Best Regards,<br/>
            <b>Human Resources</b><br/>
            Levitica Technologies Pvt Ltd
        </p>
    </div>
    """
    message = MessageSchema(
        subject="Self-Onboarding Initiated",
        recipients=[email],
        body=html_body,
        subtype=MessageType.html,
    )
    await FastMail(mail_config).send_message(message)


def build_onboarding_link(token: str) -> str:
    """Public link the candidate opens to fill the onboarding form.
    Set FRONTEND_URL in the environment (e.g. https://hr.example.com)."""
    base = os.getenv("FRONTEND_URL", "https://yourdomain.com").rstrip("/")
    return f"{base}/onboarding/{token}"


def create_onboarding_invite(
    db: Session,
    full_name: str,
    email: str | None,
    mobile: str | None,
    verification_options: list | None = None,
) -> Candidate:
    """Create the onboarding record (status SENT) with a 3-day invite token.
    Shared by the manual invite endpoint and automatic offer acceptance."""
    verification_options = verification_options or []
    candidate = Candidate(
        full_name=full_name,
        email=email,
        mobile=mobile,
        invite_token=str(uuid4()),
        token_expires_at=datetime.utcnow() + timedelta(days=3),
        status="SENT",
        verification_options=verification_options,
        credits_used=compute_credits(verification_options),
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


def _get_or_404(db: Session, candidate_id: int) -> Candidate:
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Onboarding form not found")
    return candidate




@router.get("/", response_model=PaginatedCandidates)
def list_candidates(
    status:   str | None = Query(default=None, description="Filter by status: SENT, SUBMITTED, APPROVED, REJECTED"),
    search:   str | None = Query(default=None, description="Search by name, email, or mobile"),
    page:     int        = Query(default=1,    ge=1),
    per_page: int        = Query(default=10,   ge=1, le=100),
    db: Session          = Depends(get_db),
):
    
    q = db.query(Candidate)

    
    if status and status.upper() != "ALL":
        q = q.filter(Candidate.status == status.upper())

    
    if search:
        term = f"%{search}%"
        q = q.filter(
            or_(
                Candidate.full_name.ilike(term),
                Candidate.email.ilike(term),
                Candidate.mobile.ilike(term),
            )
        )

    total = q.count()
    candidates = (
        q.order_by(Candidate.created_at.desc())
         .offset((page - 1) * per_page)
         .limit(per_page)
         .all()
    )

    return PaginatedCandidates(
        total=total,
        page=page,
        per_page=per_page,
        results=candidates,
    )




@router.get("/{candidate_id}", response_model=CandidateOut)
def get_candidate(candidate_id: int, db: Session = Depends(get_db)):
    
    return _get_or_404(db, candidate_id)




@router.post("/", status_code=status.HTTP_201_CREATED, response_model=CandidateOut)
async def invite_candidate(
    payload: CandidateCreate,
    db: Session = Depends(get_db),
):
  
    if not payload.email and not payload.mobile:
        raise HTTPException(
            status_code=400,
            detail="Either email or mobile is required",
        )

    candidate = create_onboarding_invite(
        db,
        full_name=payload.full_name,
        email=payload.email,
        mobile=payload.mobile,
        verification_options=payload.verification_options,
    )
    expiry = candidate.token_expires_at
    onboarding_link = build_onboarding_link(candidate.invite_token)

    if payload.email:
        try:
            await _send_invite_email(
                email=payload.email,
                name=payload.full_name,
                link=onboarding_link,
                expiry=expiry,
            )
        except Exception as exc:
            print("❌ Email failed:", exc)

    return candidate




@router.put("/{candidate_id}", response_model=CandidateOut)
def update_candidate(
    candidate_id: int,
    payload: CandidateUpdate,
    db: Session = Depends(get_db),
):
    candidate = _get_or_404(db, candidate_id)

    if payload.full_name is not None:
        candidate.full_name = payload.full_name

    if payload.email is not None:
        candidate.email = payload.email

    if payload.mobile is not None:
        candidate.mobile = payload.mobile

    if payload.verification_options is not None:
        candidate.verification_options = payload.verification_options
        candidate.credits_used = compute_credits(payload.verification_options)

    candidate.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(candidate)

    return candidate




@router.put("/{candidate_id}/approve", response_model=CandidateOut)
def approve_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
):
    candidate = _get_or_404(db, candidate_id)

    if candidate.status not in ("SUBMITTED", "SENT"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve a form with status '{candidate.status}'",
        )

    candidate.status     = "APPROVED"
    candidate.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(candidate)

    return candidate




@router.put("/{candidate_id}/reject", response_model=CandidateOut)
def reject_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
):
    candidate = _get_or_404(db, candidate_id)

    if candidate.status != "SUBMITTED":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reject a form with status '{candidate.status}'",
        )

    candidate.status     = "REJECTED"
    candidate.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(candidate)

    return candidate




@router.delete("/{candidate_id}")
def delete_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
):
    candidate = _get_or_404(db, candidate_id)

    db.delete(candidate)
    db.commit()

    return {
        "message": f"Onboarding form for '{candidate.full_name}' has been permanently deleted.",
        "deleted_id": candidate_id,
    }