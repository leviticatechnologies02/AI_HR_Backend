import io
import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session, select
from starlette.datastructures import Headers

from core.database import get_db
from model.models import Job, Application, Candidate
from .auth import get_current_candidate

router = APIRouter(tags=["Candidate Apply"])

# The screening JD is generated from role + experience level. Jobs do not
# store an experience level, so this default is used for auto-screening.
DEFAULT_EXPERIENCE_LEVEL = os.getenv("DEFAULT_EXPERIENCE_LEVEL", "Mid-level")
UPLOAD_DIR = "uploads"


def _load_saved_resume(candidate: Candidate):
    """Return (filename, bytes) of a resume saved earlier for this candidate."""
    path = candidate.resume_url
    if path and os.path.isfile(path):
        with open(path, "rb") as fh:
            return os.path.basename(path), fh.read()
    return None, None


async def _auto_screen(db: Session, job: Job, candidate: Candidate, filename: str, content: bytes) -> dict:
    """
    Run the same screening used by the recruiter's manual upload
    (/process: parse -> AI score -> threshold -> stage + shortlist email).
    Applying must never fail because screening failed, so every error is
    caught and reported in the response instead.
    """
    try:
        # Imported here so a missing OpenAI/SMTP env does not stop the
        # whole candidates router from loading.
        from routers.Resume_parsing.routers.resume_router import process_resume
    except Exception as exc:
        return {"status": "skipped", "reason": f"screening unavailable: {exc}"}

    upload = UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": "application/octet-stream"}),
    )
    try:
        response = await process_resume(
            file=upload,
            role=job.role or job.title,
            experience_level=DEFAULT_EXPERIENCE_LEVEL,
            candidate_id=candidate.id,
            candidate_email=candidate.email,
            db=db,
        )
        body = json.loads(response.body)
        return {
            "status": body.get("status"),          # shortlisted | rejected
            "score": body.get("score"),
            "threshold": body.get("threshold"),
            "email_status": body.get("email_status"),
        }
    except HTTPException as exc:
        # e.g. 400 "already been screened", 503 AI service unavailable
        db.rollback()
        return {"status": "pending", "reason": str(exc.detail)}
    except Exception as exc:
        db.rollback()
        return {"status": "pending", "reason": f"screening failed: {exc}"}


@router.post("/{job_id}", status_code=201)
async def apply_to_job(
    job_id: int,
    resume: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    candidate: Candidate = Depends(get_current_candidate),
):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "Draft":
        raise HTTPException(status_code=404, detail="Job not found")

    existing = db.exec(
        select(Application).where(
            Application.job_id == job_id,
            Application.candidate_id == candidate.id,
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="You have already applied to this job")

    # Resume: a newly uploaded file wins, otherwise reuse one saved earlier.
    filename, content = None, None
    if resume is not None and resume.filename:
        filename = os.path.basename(resume.filename)
        content = await resume.read()
        if content:
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            with open(os.path.join(UPLOAD_DIR, filename), "wb") as fh:
                fh.write(content)
            candidate.resume_url = f"{UPLOAD_DIR}/{filename}"
            db.add(candidate)
        else:
            filename, content = None, None
    if not content:
        filename, content = _load_saved_resume(candidate)

    application = Application(
        job_id=job_id,
        candidate_id=candidate.id,
        candidate_name=candidate.name,
        candidate_email=candidate.email,
        stage="Applied",
        source="Career Page",
    )
    db.add(application)
    db.commit()
    db.refresh(application)

    if content:
        screening = await _auto_screen(db, job, candidate, filename, content)
    else:
        screening = {
            "status": "pending",
            "reason": "No resume attached. Upload a resume to be screened automatically.",
        }

    db.refresh(application)
    return {
        "message": "Application submitted successfully",
        "application_id": application.id,
        "job_id": job_id,
        "candidate_id": candidate.id,
        "stage": application.stage,
        "screening": screening,
    }
