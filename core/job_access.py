"""
Which jobs a user may see. One rule, used by every job-scoped screen
(job list, candidates, screening, pipeline, assessment results):

  recruiter                      -> only jobs they created
  company / admin / hr_admin     -> jobs created by recruiters of their own company (tenant)
  admin with no company linked   -> everything (legacy behaviour, so nobody is locked out)
  superadmin                     -> everything
"""
from sqlalchemy import or_, select as sa_select

from model.models import Job, User


def sees_all_jobs(user: User) -> bool:
    role = (user.role or "").lower()
    return role == "superadmin" or (role == "admin" and user.tenant_id is None)


def visible_jobs_clause(user: User):
    """SQL condition for the jobs this user is allowed to see or manage."""
    if sees_all_jobs(user):
        return Job.id.isnot(None)
    role = (user.role or "").lower()
    if role in ("company", "admin", "hr_admin") and user.tenant_id is not None:
        same_company = sa_select(User.id).where(User.tenant_id == user.tenant_id)
        return or_(Job.recruiter_id == user.id, Job.recruiter_id.in_(same_company))
    return Job.recruiter_id == user.id
