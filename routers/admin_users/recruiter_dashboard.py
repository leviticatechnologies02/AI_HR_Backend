from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from typing import List, Optional
from datetime import datetime, timedelta

from core.database import get_db
from core.dependencies import require_roles
from core.job_access import visible_jobs_clause
from model.models import Job, Candidate, User, Application, CandidateRecord
from schema.schemas import JobCreate, JobRead, JobUpdate, CandidateRead

router = APIRouter()

# Who may use the dashboard endpoints. Creating a job stays recruiter/admin only.
# What each role actually sees is decided by visible_jobs_clause (own jobs / their company / their branch).
DASHBOARD_ROLES = ["recruiter", "admin", "company", "hr_admin", "superadmin"]


def _visible_job(db: Session, user: User, job_id: int):
    return db.execute(
        select(Job).where(Job.id == job_id, visible_jobs_clause(user))
    ).scalar_one_or_none()




@router.post("/jobs", response_model=JobRead)
def create_job(
    payload: JobCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(["recruiter", "admin"]))
):
    now = datetime.utcnow()
    job = Job(
        **payload.dict(),
        recruiter_id=user.id,
        created_at=now,
        updated_at=now
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.get("/jobs", response_model=List[JobRead])
def list_jobs(
    status: Optional[str] = Query(None),
    title: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(DASHBOARD_ROLES))
):
    stmt = select(Job).where(visible_jobs_clause(user))

    if status:
        stmt = stmt.where(Job.status.ilike(f"%{status}%"))
    if title:
        stmt = stmt.where(Job.title.ilike(f"%{title}%"))
    if location:
        stmt = stmt.where(Job.location.ilike(f"%{location}%"))
    if start_date:
        stmt = stmt.where(Job.created_at >= start_date)
    if end_date:
        stmt = stmt.where(Job.created_at <= end_date)

    return db.execute(stmt).scalars().all()


@router.get("/jobs/{job_id}", response_model=JobRead)
def job_detail(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(DASHBOARD_ROLES))
):
    job = _visible_job(db, user, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.put("/jobs/{job_id}", response_model=JobRead)
def update_job(
    job_id: int,
    payload: JobUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(DASHBOARD_ROLES))
):
    job = _visible_job(db, user, job_id)
    if not job:
        raise HTTPException(404, "Job not found or unauthorized")

    for key, value in payload.dict(exclude_unset=True).items():
        setattr(job, key, value)

    job.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    return job


@router.delete("/jobs/{job_id}")
def delete_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(DASHBOARD_ROLES))
):
    job = _visible_job(db, user, job_id)
    if not job:
        raise HTTPException(404, "Job not found or unauthorized")

    db.delete(job)
    db.commit()
    return {"detail": "Job deleted"}




@router.get("/candidates")
def list_candidates(
    skills: Optional[str] = Query(None),
    job_id: Optional[int] = None,
    stage: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(DASHBOARD_ROLES))
):
 
    job_ids = db.execute(
        select(Job.id).where(visible_jobs_clause(user))
    ).scalars().all()

    if not job_ids:
        return []

    
    app_stmt = select(Application).where(Application.job_id.in_(job_ids))
    if job_id:
        app_stmt = app_stmt.where(Application.job_id == job_id)

    applications = db.execute(app_stmt).scalars().all()
    candidate_ids = list({app.candidate_id for app in applications})

    if not candidate_ids:
        return []

  
    cand_stmt = select(Candidate).where(Candidate.id.in_(candidate_ids))
    if stage:
        cand_stmt = cand_stmt.where(Candidate.stage == stage)
    if skills:
        cand_stmt = cand_stmt.where(Candidate.skills.ilike(f"%{skills}%"))

    candidates = db.execute(cand_stmt).scalars().all()

    
    emails = [c.email.lower().strip() for c in candidates if c.email]
    screened_map = {}

    if emails:
        records = db.execute(
            select(CandidateRecord).where(
                func.lower(func.trim(CandidateRecord.candidate_email)).in_(emails)
            )
        ).scalars().all()

        for r in records:
            key = (r.candidate_email or "").lower().strip()
            if not key:
                continue
            current_value = screened_map.get(key)
            new_value = (r.resume_screened or "no").lower().strip()
           
            if current_value == "yes" or new_value == "yes":
                screened_map[key] = "yes"
            else:
                screened_map[key] = "no"

    
    return [
        {
            "id": c.id,
            "name": c.name,
            "email": c.email,
            "role": c.role,
            "skills": c.skills,
            "stage": c.stage,
            "resume_url": c.resume_url,
            "notes": c.notes,
            "recruiter_comments": c.recruiter_comments,
            "resume_screened": (
                "yes" if screened_map.get(c.email.lower().strip(), "no") == "yes" else "no"
            ) if c.email else "no"
        }
        for c in candidates
    ]


@router.get("/pipeline/{job_id}")
def pipeline_view(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(DASHBOARD_ROLES))
):
    job = _visible_job(db, user, job_id)
    if not job:
        raise HTTPException(404, "Job not found or unauthorized")

    rows = db.execute(
        select(Candidate.stage, func.count(Candidate.id))
        .join(Application, Application.candidate_id == Candidate.id)
        .where(Application.job_id == job_id)
        .group_by(Candidate.stage)
    ).all()

    return {stage: count for stage, count in rows}



@router.get("/analytics/applications-over-time")
def applications_over_time(
    days: int = 30,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(DASHBOARD_ROLES))
):
    start_date = datetime.utcnow() - timedelta(days=days)

    job_ids = db.execute(
        select(Job.id).where(visible_jobs_clause(user))
    ).scalars().all()

    if not job_ids:
        return []

    rows = db.execute(
        select(func.date(Candidate.created_at), func.count(Candidate.id))
        .join(Application, Application.candidate_id == Candidate.id)
        .where(
            Application.job_id.in_(job_ids),
            Candidate.created_at >= start_date
        )
        .group_by(func.date(Candidate.created_at))
        .order_by(func.date(Candidate.created_at))
    ).all()

    return [{"date": d, "count": c} for d, c in rows]




@router.get("/settings")
def recruiter_settings(user: User = Depends(require_roles(DASHBOARD_ROLES))):
    return {
        "user_id": user.id,
        "email": user.email,
        "role": user.role
    }
