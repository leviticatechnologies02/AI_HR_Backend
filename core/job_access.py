"""
Which jobs a user may see, and which branch a job belongs to. One rule, used by every job-scoped screen
(job list, candidates, screening, pipeline, assessment results):

  recruiter                      -> only jobs they created
  company / admin / hr_admin     -> jobs created by recruiters of their own company (tenant)
  admin tied to a branch         -> only jobs of THEIR branch (forced, cannot be widened)
  company / superadmin           -> may narrow to one branch (X-Location-Id header from the branch selector)
  admin with no company linked   -> everything (legacy behaviour, so nobody is locked out)
  superadmin                     -> everything

A job belongs to a branch through Job.location_id (picked on the Create Job form). Jobs that have no
location_id yet (created before that column existed) still match their branch by the free-text location
("Hyderabad", "Hitech City, Hyderabad") or, failing that, by the recruiter's own branch.
"""
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select as sa_select

from model.Company_Settings.location import CompanyLocation
from model.models import Job, User


def sees_all_jobs(user: User) -> bool:
    role = (user.role or "").lower()
    return role == "superadmin" or (role == "admin" and user.tenant_id is None)


def jobs_in_branch(location_id: int):
    """SQL condition: the job belongs to this branch."""
    branch_name = (
        sa_select(func.lower(func.trim(CompanyLocation.name)))
        .where(CompanyLocation.id == location_id)
        .scalar_subquery()
    )
    recruiters_in_branch = sa_select(User.id).where(User.location_id == location_id)
    return or_(
        Job.location_id == location_id,                                  # explicit branch (new jobs)
        and_(                                                            # legacy jobs without a branch id
            Job.location_id.is_(None),
            or_(
                func.lower(func.trim(Job.location)).contains(branch_name),
                Job.recruiter_id.in_(recruiters_in_branch),
            ),
        ),
    )


def visible_jobs_clause(user: User, location_id: Optional[int] = None):
    """SQL condition for the jobs this user is allowed to see or manage.
    location_id is an optional branch filter (ignored for recruiters)."""
    role = (user.role or "").lower()

    # A branch-locked admin is always limited to their own branch.
    if role == "admin" and user.location_id is not None:
        location_id = user.location_id
    # Company / super admin: the branch picked in the top-bar selector (X-Location-Id header).
    elif location_id is None and role in ("company", "superadmin"):
        location_id = getattr(user, "selected_location_id", None)

    if sees_all_jobs(user):
        base = Job.id.isnot(None)
    elif role in ("company", "admin", "hr_admin") and user.tenant_id is not None:
        same_company = sa_select(User.id).where(User.tenant_id == user.tenant_id)
        base = or_(Job.recruiter_id == user.id, Job.recruiter_id.in_(same_company))
    else:
        return Job.recruiter_id == user.id        # recruiter, or no company linked

    if location_id is not None:
        return and_(base, jobs_in_branch(location_id))
    return base


def resolve_job_branch(db, user: User, branch_id: Optional[int], location_text: Optional[str]) -> Optional[int]:
    """Decide which branch a job being created/edited belongs to.
      1. an explicit branch id from the form (must be an active branch of the user's company);
      2. else the branch whose name appears in the free-text location;
      3. else the recruiter's own branch (may be None)."""
    branches = []
    if user.tenant_id is not None:
        branches = db.execute(
            sa_select(CompanyLocation).where(
                CompanyLocation.tenant_id == user.tenant_id, CompanyLocation.is_active.is_(True)
            )
        ).scalars().all()

    if branch_id is not None:
        if not any(b.id == branch_id for b in branches):
            raise HTTPException(status_code=400, detail="That branch does not belong to your company.")
        return branch_id

    text = (location_text or "").strip().lower()
    if text:
        for b in branches:                       # exact name first, then "name appears in the text"
            if (b.name or "").strip().lower() == text:
                return b.id
        for b in branches:
            if (b.name or "").strip().lower() and (b.name or "").strip().lower() in text:
                return b.id

    return user.location_id
