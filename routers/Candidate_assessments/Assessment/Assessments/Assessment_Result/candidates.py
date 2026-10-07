from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import model.models
from core.database import get_db
from core.dependencies import get_current_user
from model.models import User, Job, Application
from sqlmodel import select
from core.job_access import sees_all_jobs, visible_jobs_clause
from schema import schemas


router = APIRouter(prefix="/api/candidates",tags=["candidates"])

@router.get("/", response_model=list[schemas.CandidateSchema])
def read_candidates(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    
    if sees_all_jobs(user):
        return db.query(model.models.Candidate).all()
    
    job_ids = list(db.exec(select(Job.id).where(visible_jobs_clause(user))).all())
    
    if not job_ids:
        return []
    
    
    applications = db.exec(select(Application).where(Application.job_id.in_(job_ids))).all()
    candidate_ids = list(set([app.candidate_id for app in applications if app.candidate_id]))
    
    if not candidate_ids:
        return []
    
   
    return db.query(model.models.Candidate).filter(model.models.Candidate.id.in_(candidate_ids)).all()

@router.get("/{candidate_id}", response_model=schemas.CandidateSchema)
def read_candidate(candidate_id: int, db: Session = Depends(get_db)):
    candidate = db.query(model.models.Candidate).filter(model.models.Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate
