"""
Which jobs a user may see. One rule, used by every job-scoped screen
(job list, candidates, screening, pipeline, assessment results):

  recruiter                      -> only jobs they created
  company / admin / hr_admin     -> jobs created by recruiters of their own company (tenant)
  admin tied to a branch         -> only recruiters of THEIR branch (forced, cannot be widened)
  company / superadmin           -> may narrow to one branch (X-Location-Id header from the branch selector)
  admin with no company linked   -> everything (legacy behaviour, so nobody is locked out)
  superadmin                     -> everything
"""
from typing import Optional

from sqlalchemy import and_, func, or_, select as sa_select

from model.models import Job, User
from model.Company_Settings.location import CompanyLocation


def sees_all_jobs(user: User) -> bool:
    role = (user.role or "").lower()
    return role == "superadmin" or (role == "admin" and user.tenant_id is None)


def visible_jobs_clause(user: User, location_id: Optional[int] = None):
    """SQL condition for the jobs this user is allowed to see or manage.
    location_id is an optional branch filter (ignored for recruiters)."""
    role = (user.role or "").lower()

    # A branch-locked admin is always limited to their own branch.
    if role == "admin" and user.location_id is not None:
        location_id = user.location_id

    if sees_all_jobs(user):
        base = Job.id.isnot(None)
    elif role in ("company", "admin", "hr_admin") and user.tenant_id is not None:
        same_company = sa_select(User.id).where(User.tenant_id == user.tenant_id)
        base = or_(Job.recruiter_id == user.id, Job.recruiter_id.in_(same_company))
    else:
        return Job.recruiter_id == user.id        # recruiter, or no company linked

    if location_id is not None:
        # A job belongs to a branch if EITHER its recruiter is assigned to that
        # branch, OR the job's own free-text "location" names that branch
        # (branch name or city, case-insensitive). The second rule is what makes
        # jobs from recruiters with no branch assigned still show up when a
        # branch like "Hyderabad" is picked in the selector.
        in_branch = sa_select(User.id).where(User.location_id == location_id)
        branch_name = sa_select(func.lower(CompanyLocation.name)).where(
            CompanyLocation.id == location_id).scalar_subquery()
        branch_city = sa_select(func.lower(CompanyLocation.city)).where(
            CompanyLocation.id == location_id).scalar_subquery()
        job_loc = func.lower(func.coalesce(Job.location, ""))
        by_text = or_(
            job_loc == branch_name,
            and_(branch_name != "", job_loc.contains(branch_name, autoescape=True)),
            and_(branch_city.isnot(None), branch_city != "", job_loc.contains(branch_city, autoescape=True)),
        )
        return and_(base, or_(Job.recruiter_id.in_(in_branch), by_text))
    return base