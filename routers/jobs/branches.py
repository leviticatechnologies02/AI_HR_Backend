from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.database import get_db
from model.Company_Settings.location import CompanyLocation
from model.models import User
from .dependencies import require_roles, JOB_VIEW_ROLES

router = APIRouter(tags=["Jobs"])


@router.get("/branches")
def list_job_branches(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(JOB_VIEW_ROLES)),
):
    """The company's active branches, for the Location dropdown on the Create Job form.
    (A recruiter cannot use the company-settings endpoint, which is for company/admin only.)"""
    if user.tenant_id is None:
        return []
    rows = db.execute(
        select(CompanyLocation)
        .where(CompanyLocation.tenant_id == user.tenant_id, CompanyLocation.is_active.is_(True))
        .order_by(CompanyLocation.is_default.desc(), CompanyLocation.name)
    ).scalars().all()
    return [
        {"id": b.id, "name": b.name, "city": getattr(b, "city", None), "is_default": bool(b.is_default),
         "is_own_branch": b.id == user.location_id}
        for b in rows
    ]
