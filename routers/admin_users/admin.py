from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from pydantic import BaseModel, EmailStr
from typing import Optional, Literal

from core.database import get_db
from model.Company_Settings.location import CompanyLocation
from model.models import User, Job
from routers.admin_users.auth import require_roles, get_password_hash

router = APIRouter(prefix="/superadmin", tags=["Admin"]) 
compat_router = APIRouter(prefix="/admin/user", tags=["Admin"])


ROLE_CHOICES = Literal["recruiter", "company", "admin", "hr_admin", "candidate", "superadmin"]


class AdminUserCreate(BaseModel):
    name: str
    username: Optional[str] = None
    email: EmailStr
    role: ROLE_CHOICES
    is_active: bool = False
    password: Optional[str] = None
    tenant_id: Optional[int] = None
    location_id: Optional[int] = None      # branch (CompanyLocation.id); admin / recruiter / hr_admin only


class AdminUserUpdate(BaseModel):
    name: Optional[str]
    username: Optional[str]
    email: Optional[EmailStr]
    role: Optional[ROLE_CHOICES]
    is_active: Optional[bool]
    password: Optional[str] = None
    tenant_id: Optional[int] = None
    location_id: Optional[int] = None


BRANCH_ROLES = {"admin", "recruiter", "hr_admin"}


def _check_branch(db: Session, role: str, tenant_id: Optional[int], location_id: Optional[int]) -> Optional[int]:
    """Return the location_id to store. A branch only applies to branch-level roles and must
    belong to the user's company."""
    if location_id is None or role not in BRANCH_ROLES:
        return None
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="Pick a company before choosing a branch.")
    loc = db.get(CompanyLocation, location_id)
    if not loc or loc.tenant_id != tenant_id or not loc.is_active:
        raise HTTPException(status_code=400, detail="That branch does not belong to the selected company.")
    return location_id


def _serialize_user(user: User, db: Optional[Session] = None) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "tenant_id": user.tenant_id,
        "location_id": user.location_id,
        "branch_name": (db.get(CompanyLocation, user.location_id).name
                        if db is not None and user.location_id and db.get(CompanyLocation, user.location_id) else None),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }

@router.get("/summary")
def admin_summary(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(["superadmin"])),
):
    total_users = db.execute(select(func.count(User.id))).scalar_one()
    users = db.execute(select(User)).scalars().all()

    return {
        "total_users": total_users,
        "users": [_serialize_user(u, db) for u in users]
    }


@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(["superadmin"]))
):
    users = db.execute(select(User)).scalars().all()
    return [_serialize_user(u, db) for u in users]


@compat_router.get("/list")
def list_users_compat(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(["superadmin"]))
):
    users = db.execute(select(User)).scalars().all()
    return [_serialize_user(u, db) for u in users]


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AdminUserCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(["superadmin"]))
):
    existing = db.execute(select(User).where(User.email == payload.email)).scalars().first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    tenant_scoped_roles = {"admin", "hr_admin", "recruiter", "company"}
    if payload.role in tenant_scoped_roles and not payload.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{payload.role}' must be linked to a company (tenant_id) — pick one from Tenant Management.",
        )

    hashed_password = get_password_hash(payload.password or "ChangeMe@123")

    new_user = User(
        name=payload.name,
        username=payload.username,
        email=payload.email,
        role=payload.role,
        is_active=payload.is_active,
        hashed_password=hashed_password,
        tenant_id=payload.tenant_id,
        location_id=_check_branch(db, payload.role, payload.tenant_id, payload.location_id),
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return _serialize_user(new_user, db)


@router.put("/users/{user_id}")
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["superadmin"]))
):
    target_user = db.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if payload.email and payload.email != target_user.email:
        duplicate = db.execute(select(User).where(User.email == payload.email)).scalars().first()
        if duplicate:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    if payload.password:
        target_user.hashed_password = get_password_hash(payload.password)

    for field in ["name", "username", "email", "role", "is_active", "tenant_id"]:
        value = getattr(payload, field)
        if value is not None:
            setattr(target_user, field, value)

    # Branch follows the (possibly changed) role/company. Sending location_id=null clears it.
    if "location_id" in payload.model_fields_set or "role" in payload.model_fields_set or "tenant_id" in payload.model_fields_set:
        wanted = payload.location_id if "location_id" in payload.model_fields_set else target_user.location_id
        target_user.location_id = _check_branch(db, target_user.role, target_user.tenant_id, wanted)

    db.add(target_user)
    db.commit()
    db.refresh(target_user)

    return _serialize_user(target_user, db)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["superadmin"]))
):
    target_user = db.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    has_jobs = db.execute(select(Job).where(Job.recruiter_id == target_user.id)).scalars().first()
    if has_jobs:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete recruiter while jobs reference them. Reassign or remove those jobs first."
        )

    db.delete(target_user)
    db.commit()