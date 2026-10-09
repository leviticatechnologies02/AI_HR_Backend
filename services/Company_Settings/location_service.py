
from __future__ import annotations
from typing import List, Optional
import logging

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from model.Company_Settings.location import CompanyLocation
from model.onboarding.employee import Employee
from schema.Company_Settings.location import (
    CompanyLocationCreate,
    CompanyLocationUpdate,
)

logger = logging.getLogger(__name__)


def _attach_employee_count(db: Session, locations: List[CompanyLocation]) -> List[CompanyLocation]:
    """Stamp a transient `employee_count` attribute onto each location for reporting.

    One grouped query instead of one per branch. If the count cannot be computed
    (e.g. employees.location_id column not migrated yet) the branch list must
    still load, so we log and fall back to 0 instead of failing the request.
    """
    counts = {}
    ids = [loc.id for loc in locations]
    if ids:
        try:
            rows = (
                db.query(Employee.location_id, func.count(Employee.id))
                .filter(Employee.location_id.in_(ids), Employee.is_active.is_(True))
                .group_by(Employee.location_id)
                .all()
            )
            counts = {loc_id: n for loc_id, n in rows}
        except Exception:
            db.rollback()
            logger.exception("Could not compute employee counts per branch; defaulting to 0")
    for loc in locations:
        loc.employee_count = counts.get(loc.id, 0)
    return locations


def get_all_locations(db: Session, tenant_id: int) -> List[CompanyLocation]:
    locations = (
        db.query(CompanyLocation)
        .filter(
            CompanyLocation.tenant_id == tenant_id,
            CompanyLocation.is_active.is_(True),
        )
        .order_by(CompanyLocation.is_default.desc(), CompanyLocation.name)
        .all()
    )
    return _attach_employee_count(db, locations)


def get_location(db: Session, tenant_id: int, location_id: int) -> CompanyLocation:
    location = _get_or_404(db, tenant_id, location_id)
    _attach_employee_count(db, [location])
    return location


def _assert_name_free(db: Session, tenant_id: int, name: str, exclude_id: Optional[int] = None) -> None:
    """A company cannot have two active branches with the same name."""
    q = db.query(CompanyLocation).filter(
        CompanyLocation.tenant_id == tenant_id,
        CompanyLocation.is_active.is_(True),
        func.lower(func.trim(CompanyLocation.name)) == name.strip().lower(),
    )
    if exclude_id is not None:
        q = q.filter(CompanyLocation.id != exclude_id)
    if q.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A branch named '{name.strip()}' already exists.",
        )


def create_location(
    db:        Session,
    tenant_id: int,
    data:      CompanyLocationCreate,
    actor_id:  Optional[int] = None,
) -> CompanyLocation:
    
    _assert_name_free(db, tenant_id, data.name)

    if data.is_default:
        _clear_default(db, tenant_id)

    location = CompanyLocation(
        tenant_id  = tenant_id,
        updated_by = actor_id,
        **data.model_dump(),
    )
    db.add(location)
    db.commit()
    db.refresh(location)
    return location


def update_location(
    db:          Session,
    tenant_id:   int,
    location_id: int,
    data:        CompanyLocationUpdate,
    actor_id:    Optional[int] = None,
) -> CompanyLocation:
    location = _get_or_404(db, tenant_id, location_id)

    if data.name is not None and data.name.strip().lower() != (location.name or "").strip().lower():
        _assert_name_free(db, tenant_id, data.name, exclude_id=location_id)

    if data.is_default:
        _clear_default(db, tenant_id)

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(location, field, value)

    location.updated_by = actor_id
    db.commit()
    db.refresh(location)
    return location


def delete_location(
    db: Session, tenant_id: int, location_id: int, actor_id: Optional[int] = None
) -> None:
    location = _get_or_404(db, tenant_id, location_id)
    if location.is_default:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the default location. Set another location as default first.",
        )
    assigned = (
        db.query(Employee)
        .filter(Employee.location_id == location_id, Employee.is_active.is_(True))
        .count()
    )
    if assigned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete this branch — {assigned} active employee(s) are still assigned to it. Reassign them first.",
        )
    location.is_active  = False
    location.updated_by = actor_id
    db.commit()


def set_default_location(
    db: Session, tenant_id: int, location_id: int, actor_id: Optional[int] = None
) -> CompanyLocation:
    location = _get_or_404(db, tenant_id, location_id)
    _clear_default(db, tenant_id)
    location.is_default  = True
    location.updated_by  = actor_id
    db.commit()
    db.refresh(location)
    return location


def _get_or_404(db: Session, tenant_id: int, location_id: int) -> CompanyLocation:
    loc = (
        db.query(CompanyLocation)
        .filter(
            CompanyLocation.id        == location_id,
            CompanyLocation.tenant_id == tenant_id,
            CompanyLocation.is_active.is_(True),
        )
        .first()
    )
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    return loc


def _clear_default(db: Session, tenant_id: int) -> None:
    (
        db.query(CompanyLocation)
        .filter(
            CompanyLocation.tenant_id == tenant_id,
            CompanyLocation.is_default.is_(True),
        )
        .update({"is_default": False}, synchronize_session="fetch")
    )
