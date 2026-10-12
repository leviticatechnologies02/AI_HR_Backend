from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload
from sqlmodel import select

from core.database import get_db
from model.models import Application, Candidate, CandidateRecord, User
from .auth import ALGORITHM, SECRET_KEY

router = APIRouter(prefix="/applications", tags=["Applications"])


def _principal(request: Request, db: Session):
    """
    Resolve the caller from the Bearer token.
    Returns ("candidate", Candidate) for candidate-portal tokens and
    ("staff", User) for recruiter/admin tokens. 401 otherwise.
    """
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(header.split(" ", 1)[1], SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    sub = payload.get("sub")
    if sub is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    if payload.get("type") == "candidate":
        cand = db.get(Candidate, int(sub))
        if not cand:
            raise HTTPException(status_code=401, detail="Candidate not found")
        return "candidate", cand
    user = db.get(User, int(sub))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return "staff", user


def _row(app: Application) -> dict:
    cand = app.candidate
    return {
        "id": app.id,
        "applicationId": app.id,
        "candidate_id": app.candidate_id,
        "candidate_name": app.candidate_name,
        "candidate_email": app.candidate_email,
        "job_id": app.job_id,
        "status": app.stage or "Applied",
        "candidate_stage": cand.stage if cand else "Applied",
        "stage": app.stage or "Applied",
        "applied_at": app.applied_at.isoformat() if app.applied_at else None,
        "role": cand.role if cand else "Not specified",
        "skills": cand.skills if cand else "",
        "resume_url": cand.resume_url if cand else None,
        "source": "application",
    }


@router.get("/")
def read_applications(request: Request, db: Session = Depends(get_db)):
    """
    Candidate token  -> only that candidate's own applications (candidate portal).
    Staff token      -> every application plus candidates/records that have not
                        applied yet (recruiter Pipeline View).
    """
    kind, who = _principal(request, db)

    if kind == "candidate":
        apps = db.exec(
            select(Application)
            .where(Application.candidate_id == who.id)
            .options(selectinload(Application.candidate))
        ).all()
        return [_row(a) for a in apps]

    email_to_record: dict[str, dict] = {}
    try:
        apps = db.exec(select(Application).options(selectinload(Application.candidate))).all()
        for app in apps:
            email = app.candidate_email.lower() if app.candidate_email else None
            if email:
                email_to_record[email] = _row(app)

        for c in db.exec(select(Candidate)).all():
            email = c.email.lower() if c.email else None
            if email and email not in email_to_record:
                stage = c.stage or "Applied"
                email_to_record[email] = {
                    "id": f"candidate_{c.id}", "applicationId": None, "candidate_id": c.id,
                    "candidate_name": c.name, "candidate_email": c.email, "job_id": None,
                    "status": stage, "candidate_stage": stage, "stage": stage,
                    "applied_at": None, "role": c.role or "Not specified",
                    "skills": c.skills or "", "resume_url": c.resume_url, "source": "candidate",
                }

        for r in db.exec(select(CandidateRecord)).all():
            email = r.candidate_email.lower() if r.candidate_email else None
            if email:
                stage = r.stage or "Applied"
                email_to_record[email] = {
                    "id": f"candidate_record_{r.id}", "applicationId": None, "candidate_id": None,
                    "candidate_name": r.candidate_name, "candidate_email": r.candidate_email,
                    "job_id": None, "status": stage, "candidate_stage": stage, "stage": stage,
                    "applied_at": r.created_at.isoformat() if r.created_at else None,
                    "role": r.role or "Not specified", "skills": r.candidate_skills or "",
                    "resume_url": None, "source": "candidate_record",
                }
        return list(email_to_record.values())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ApplicationStageUpdate(BaseModel):
    stage: Optional[str] = None
    status: Optional[str] = None  # legacy: "applied" | "pipeline" | "hired"


_LEGACY_STATUS = {"applied": "Applied", "pipeline": "Screening", "hired": "Hired"}


@router.patch("/{app_id}")
def update_application_stage(
    app_id: int,
    payload: ApplicationStageUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Used by the Pipeline View drag & drop. Staff only."""
    kind, _ = _principal(request, db)
    if kind != "staff":
        raise HTTPException(status_code=403, detail="Operation not permitted")

    app = db.get(Application, app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    new_stage = payload.stage or _LEGACY_STATUS.get((payload.status or "").lower(), payload.status)
    if not new_stage:
        raise HTTPException(status_code=422, detail="stage or status is required")

    app.stage = new_stage
    app.updated_at = datetime.utcnow()
    if new_stage.lower() == "hired" and not app.hired_at:
        app.hired_at = datetime.utcnow()

    cand = db.get(Candidate, app.candidate_id)
    if cand:  # the pipeline board groups cards by Candidate.stage
        cand.stage = new_stage
        db.add(cand)

    db.add(app)
    db.commit()
    db.refresh(app)
    return {"id": app.id, "stage": app.stage}


@router.patch("/by-candidate/{candidate_id}")
def update_candidate_stage(
    candidate_id: int,
    payload: ApplicationStageUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Pipeline drag & drop for a candidate who has no Application row yet. Staff only."""
    kind, _ = _principal(request, db)
    if kind != "staff":
        raise HTTPException(status_code=403, detail="Operation not permitted")
    cand = db.get(Candidate, candidate_id)
    if not cand:
        raise HTTPException(status_code=404, detail="Candidate not found")
    new_stage = payload.stage or _LEGACY_STATUS.get((payload.status or "").lower(), payload.status)
    if not new_stage:
        raise HTTPException(status_code=422, detail="stage or status is required")
    cand.stage = new_stage
    db.add(cand)
    for app in db.exec(select(Application).where(Application.candidate_id == candidate_id)).all():
        app.stage = new_stage
        app.updated_at = datetime.utcnow()
        if new_stage.lower() == "hired" and not app.hired_at:
            app.hired_at = datetime.utcnow()
        db.add(app)
    db.commit()
    return {"candidate_id": cand.id, "stage": cand.stage}


@router.delete("/{app_id}", status_code=204)
def delete_application(app_id: int, request: Request, db: Session = Depends(get_db)):
    kind, _ = _principal(request, db)
    if kind != "staff":
        raise HTTPException(status_code=403, detail="Operation not permitted")
    app = db.get(Application, app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    db.delete(app)
    db.commit()
