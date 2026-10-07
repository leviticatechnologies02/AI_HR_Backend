from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
import model.models
from core.database import get_db
from core.dependencies import get_current_user
from model.models import User, Job, Application, Candidate
from sqlmodel import select
from core.job_access import sees_all_jobs, visible_jobs_clause


router = APIRouter(prefix="/candidates", tags=["Pipeline"])


class PipelineCandidateOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    stage: str
    skills: Optional[str] = None
    resume_url: Optional[str] = None
    notes: Optional[str] = None
    recruiter_comments: Optional[str] = None

    class Config:
        from_attributes = True


class PipelineCandidateCreate(BaseModel):
    name: str
    email: str
    role: str
    stage: Optional[str] = "Applied"
    skills: Optional[str] = None
    resume_url: Optional[str] = None
    notes: Optional[str] = None


class PipelineCandidateUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    stage: Optional[str] = None
    skills: Optional[str] = None
    notes: Optional[str] = None
    recruiter_comments: Optional[str] = None


@router.get("/", response_model=List[PipelineCandidateOut])
def list_candidates(db: Session = Depends(get_db), user: User = Depends(get_current_user)):

    if sees_all_jobs(user):
        job_ids = list(db.exec(select(Job.id)).all())
    else:
        job_ids = list(db.exec(select(Job.id).where(visible_jobs_clause(user))).all())

    if not job_ids:
        return []

    applications = db.exec(select(Application).where(Application.job_id.in_(job_ids))).all()
    candidate_ids = list(set([app.candidate_id for app in applications if app.candidate_id]))

    if not candidate_ids:
        return []

    return db.query(Candidate).filter(Candidate.id.in_(candidate_ids)).all()


@router.post("/", response_model=PipelineCandidateOut, status_code=201)
def create_candidate(payload: PipelineCandidateCreate, db: Session = Depends(get_db)):
    candidate = Candidate(
        name=payload.name,
        email=payload.email,
        role=payload.role,
        stage=payload.stage or "Applied",
        skills=payload.skills,
        resume_url=payload.resume_url,
        notes=payload.notes,
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


@router.patch("/{candidate_id}", response_model=PipelineCandidateOut)
def update_candidate(candidate_id: int, payload: PipelineCandidateUpdate, db: Session = Depends(get_db)):
    candidate = db.get(Candidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    for field, value in payload.dict(exclude_unset=True).items():
        setattr(candidate, field, value)

    db.commit()
    db.refresh(candidate)
    return candidate


@router.delete("/{candidate_id}", status_code=204)
def delete_candidate(candidate_id: int, db: Session = Depends(get_db)):
    candidate = db.get(Candidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    db.delete(candidate)
    db.commit()
    return None


# ---------------- COLLABORATION COMMENTS ----------------

class CommentCreate(BaseModel):
    author: str
    text: str


class CommentOut(BaseModel):
    id: int
    candidate_id: int
    author: str
    text: str
    created_at: str

    class Config:
        from_attributes = True


@router.get("/{candidate_id}/comments", response_model=List[CommentOut])
def list_comments(candidate_id: int, db: Session = Depends(get_db)):
    comments = db.exec(
        select(model.models.CandidateComment)
        .where(model.models.CandidateComment.candidate_id == candidate_id)
        .order_by(model.models.CandidateComment.created_at)
    ).all()
    return [
        CommentOut(id=c.id, candidate_id=c.candidate_id, author=c.author, text=c.text, created_at=c.created_at.isoformat())
        for c in comments
    ]


@router.post("/{candidate_id}/comments", response_model=CommentOut, status_code=201)
def add_comment(candidate_id: int, payload: CommentCreate, db: Session = Depends(get_db)):
    candidate = db.get(Candidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    comment = model.models.CandidateComment(candidate_id=candidate_id, author=payload.author, text=payload.text)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return CommentOut(id=comment.id, candidate_id=comment.candidate_id, author=comment.author, text=comment.text, created_at=comment.created_at.isoformat())