from __future__ import annotations
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.database import get_db
from core.dependencies import get_current_user, require_roles, get_branch_lock
from model.models import User
from schema.Company_Settings.location import (
    CompanyLocationCreate,
    CompanyLocationUpdate,
    CompanyLocationResponse,
    CompanyLocationListResponse,
)
from services.Company_Settings.location_service import (
    get_all_locations,
    get_location,
    create_location,
    update_location,
    delete_location,
    set_default_location,
)

router = APIRouter(
    prefix="/company-settings/locations",
    tags=["Company Settings – Locations"],
)


def _assert_branch_access(admin_location_id, location_id: int):
    """A branch-scoped admin (admin_location_id set) may only touch their own
    branch. Whole-company admins (admin_location_id is None) are unrestricted
    here — this only fires for branch-restricted admins. (hr_admin no longer
    reaches this router at all — see the require_roles(["admin", "company"]) below.)"""
    if admin_location_id is not None and admin_location_id != location_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage your own branch.",
        )


@router.get("/", response_model=CompanyLocationListResponse)
def list_locations(
    current_user:      User    = Depends(get_current_user),
    db:                Session = Depends(get_db),
    admin_location_id: int | None = Depends(get_branch_lock),
):
    locations = get_all_locations(db, current_user.tenant_id)
    if admin_location_id is not None:
        # Branch-scoped admin: only their own branch shows up.
        locations = [loc for loc in locations if loc.id == admin_location_id]
    return CompanyLocationListResponse(locations=locations, total=len(locations))


@router.get("/{location_id}", response_model=CompanyLocationResponse)
def read_location(
    location_id:       int,
    current_user:      User    = Depends(get_current_user),
    db:                Session = Depends(get_db),
    admin_location_id: int | None = Depends(get_branch_lock),
):
    _assert_branch_access(admin_location_id, location_id)
    return get_location(db, current_user.tenant_id, location_id)


@router.post("/", response_model=CompanyLocationResponse, status_code=status.HTTP_201_CREATED)
def add_location(
    data:              CompanyLocationCreate,
    current_user:      User    = Depends(require_roles(["admin", "company"])),
    db:                Session = Depends(get_db),
    admin_location_id: int | None = Depends(get_branch_lock),
):
    # Creating a *new* branch is a whole-company action, not something a
    # single-branch admin should be able to do.
    if admin_location_id is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Branch admins cannot create new branches — contact your company admin.",
        )
    return create_location(db, current_user.tenant_id, data, current_user.id)


@router.put("/{location_id}", response_model=CompanyLocationResponse)
def edit_location(
    location_id:       int,
    data:              CompanyLocationUpdate,
    current_user:      User    = Depends(require_roles(["admin", "company"])),
    db:                Session = Depends(get_db),
    admin_location_id: int | None = Depends(get_branch_lock),
):
    _assert_branch_access(admin_location_id, location_id)
    return update_location(db, current_user.tenant_id, location_id, data, current_user.id)


@router.delete("/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_location(
    location_id:       int,
    current_user:      User    = Depends(require_roles(["admin", "company"])),
    db:                Session = Depends(get_db),
    admin_location_id: int | None = Depends(get_branch_lock),
):
    # Deleting a branch (even your own) is also a whole-company decision —
    # a branch admin managing their branch's day-to-day shouldn't be able to
    # delete the branch out from under themselves.
    if admin_location_id is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Branch admins cannot delete branches — contact your company admin.",
        )
    delete_location(db, current_user.tenant_id, location_id, current_user.id)


@router.patch("/{location_id}/set-default", response_model=CompanyLocationResponse)
def mark_default(
    location_id:       int,
    current_user:      User    = Depends(require_roles(["admin", "company"])),
    db:                Session = Depends(get_db),
    admin_location_id: int | None = Depends(get_branch_lock),
):
    if admin_location_id is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Branch admins cannot change the company's default branch.",
        )
    return set_default_location(db, current_user.tenant_id, location_id, current_user.id)