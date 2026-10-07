from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from sqlalchemy.orm import selectinload
from typing import List
from model.models import Job, User, Application
from core.database import get_db
from .dependencies import require_roles, JOB_VIEW_ROLES, visible_jobs_clause

router = APIRouter()

@router.get("/list")
def list_jobs(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(JOB_VIEW_ROLES))
):
    
    from sqlalchemy import select as sa_select
    statement = sa_select(Job).where(visible_jobs_clause(user)).options(selectinload(Job.applications))
    result = db.execute(statement)
    jobs = result.scalars().all()
    jobs_with_applications = []
    for job in jobs:
        
        job_dict = {
            "id": job.id,
            "title": job.title,
            "department": job.department or "General",
            "employment_type": job.employment_type or "Full-time",
            "location": job.location or "N/A",
            "is_remote": job.is_remote if job.is_remote is not None else False,
            "description": job.description,
            "responsibilities": job.responsibilities or "N/A",
            "requirements": job.requirements or "N/A",
            "salary_min": job.salary_min or 0,
            "salary_max": job.salary_max or 0,
            "currency": job.currency or "USD",
            "benefits": job.benefits or [],
            "skills": job.skills or [],
            "expiry_date": job.expiry_date.isoformat() if job.expiry_date else None,
            "reference_id": job.reference_id or "N/A",
            "jd_file": job.jd_file or "N/A",
            "status": job.status or "Draft",
            "recruiter_id": job.recruiter_id,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
            "applications": [
                {
                    "id": app.id,
                    "candidate_id": app.candidate_id,
                    "candidate_name": app.candidate_name,
                    "candidate_email": app.candidate_email,
                    "stage": app.stage if app.stage else "Applied",
                    "applied_at": app.applied_at.isoformat() if app.applied_at else None,
                    "candidate_stage": app.candidate.stage if app.candidate else "Applied"
                }
                for app in job.applications
            ]
        }
        jobs_with_applications.append(job_dict)

    return jobs_with_applications
