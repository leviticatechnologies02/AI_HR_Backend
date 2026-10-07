from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from routers.admin_users.auth import get_current_user
from model.models import Job, User
from core.database import get_db
from .dependencies import require_roles, JOB_VIEW_ROLES, visible_jobs_clause

router = APIRouter()

# @router.delete("/delete/{job_id}")
# def delete_job(
#     job_id: int,
#     db: Session = Depends(get_db),
#     user: User = Depends(require_roles(["company", "recruiter"]))
# ):
#     job = db.execute(select(Job).where(Job.id == job_id, Job.recruiter_id == user.id)).first()
#     if not job:
#         raise HTTPException(status_code=404, detail="Job not found or unauthorized")

#     db.delete(job)
#     db.commit()
#     return {"detail": "Job deleted"}


@router.delete("/delete/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(JOB_VIEW_ROLES))):

    job = db.execute(
        select(Job).where(Job.id == job_id, visible_jobs_clause(user))
    ).scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    db.delete(job)
    db.commit()

    return {"message": "Job deleted successfully"}