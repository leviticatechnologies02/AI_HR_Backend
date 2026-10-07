from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from datetime import datetime
from typing import Optional, List
from model.models import Job, User
from core.database import get_db
from .dependencies import require_roles, JOB_VIEW_ROLES, visible_jobs_clause

router = APIRouter()

@router.get("/search", response_model=List[Job])
def search_jobs(
    title: Optional[str] = None,
    status: Optional[str] = None,
    location: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(JOB_VIEW_ROLES))
):
    statement = select(Job).where(visible_jobs_clause(user))
    jobs = db.exec(statement).all()

    filtered_jobs = []
    for job in jobs:
        if title and title.lower() not in job.title.lower():
            continue
        if status and status.lower() != job.status.lower():
            continue
        if location and location.lower() not in (job.location or "").lower():
            continue
        if start_date and job.created_at < start_date:
            continue
        if end_date and job.created_at > end_date:
            continue
        filtered_jobs.append(job)

    return filtered_jobs
