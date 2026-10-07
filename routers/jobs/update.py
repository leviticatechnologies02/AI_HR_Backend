

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from datetime import datetime
from typing import Optional, List
from model.models import Job, User
from core.database import get_db
from typing import Optional
from core.dependencies import get_current_location_id
from .dependencies import require_roles, JOB_VIEW_ROLES, visible_jobs_clause

router = APIRouter(tags=["Jobs"])
@router.put("/update/{job_id}", response_model=Job)
def update_job(
    job_id: int,
    title: Optional[str] = None,
    department: Optional[str] = None,
    employment_type: Optional[str] = None,
    location: Optional[str] = None,
    is_remote: Optional[bool] = None,
    description: Optional[str] = None,
    responsibilities: Optional[str] = None,
    requirements: Optional[str] = None,
    salary_min: Optional[int] = None,
    salary_max: Optional[int] = None,
    currency: Optional[str] = None,
    benefits: Optional[List[str]] = None,
    skills: Optional[List[str]] = None,
    expiry_date: Optional[datetime] = None,
    reference_id: Optional[str] = None,
    jd_file: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(JOB_VIEW_ROLES)),
    location_id: Optional[int] = Depends(get_current_location_id),
):

    result = db.execute(
        select(Job).where(Job.id == job_id, visible_jobs_clause(user, location_id))
    )

    job = result.scalars().first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found or unauthorized")

    if title is not None:
        job.title = title
    if department is not None:
        job.department = department
    if employment_type is not None:
        job.employment_type = employment_type
    if location is not None:
        job.location = location
    if is_remote is not None:
        job.is_remote = is_remote
    if description is not None:
        job.description = description
    if responsibilities is not None:
        job.responsibilities = responsibilities
    if requirements is not None:
        job.requirements = requirements
    if salary_min is not None:
        job.salary_min = salary_min
    if salary_max is not None:
        job.salary_max = salary_max
    if currency is not None:
        job.currency = currency
    if benefits is not None:
        job.benefits = benefits
    if skills is not None:
        job.skills = skills
    if expiry_date is not None:
        job.expiry_date = expiry_date
    if reference_id is not None:
        job.reference_id = reference_id
    if jd_file is not None:
        job.jd_file = jd_file
    if status is not None:
        job.status = status

    job.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(job)

    return job