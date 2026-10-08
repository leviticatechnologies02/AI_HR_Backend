from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import select
from pydantic import BaseModel, EmailStr
from typing import Optional, Literal, List
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import jwt, JWTError

from sqlalchemy import func
from core.database import get_db
from core.config import settings
from model.Company_Settings.location import CompanyLocation
from model.Company_Settings.company_profile import CompanyProfile
from model.models import User
from super_admin.multi_tenant import Tenant

import secrets
from fastapi_mail import FastMail, MessageSchema, MessageType
from core.mail import mail_config


router = APIRouter(prefix="/api/auth", tags=["Auth"])

_reset_tokens: dict = {}


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


SECRET_KEY = settings.SECRET_KEY   # from .env, never hard-coded
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    email: EmailStr
    refresh_token: Optional[str] = None
    requires_password_change: bool = False
    profile_completed: bool = True

class SignupRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: Literal["recruiter", "company", "candidate"]
    company_name: Optional[str] = None
    company_website: Optional[str] = None
    # Branch (CompanyLocation.id) the recruiter works from. Required when the
    # company already has branches; see GET /api/auth/signup-branches.
    location_id: Optional[int] = None

class LoginJSON(BaseModel):
    email: EmailStr
    password: str


class CurrentUserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: str
    is_active: bool
    requires_password_change: bool = False
    profile_completed: bool = True
    employee_id: Optional[int] = None
    location_id: Optional[int] = None
    branch_name: Optional[str] = None
    # Shown on the profile page.
    username: Optional[str] = None
    company_name: Optional[str] = None
    company_website: Optional[str] = None
    company_id: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str



def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        # Never accept a candidate-portal token as a staff token.
        if payload.get("type") == "candidate":
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.get(User, int(user_id))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account not activated by admin")

    return user


def require_roles(allowed_roles: List[str]):
    def checker(user: User = Depends(get_current_user)):
        if user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Permission denied")
        return user
    return checker


def get_or_create_tenant(db: Session, company_name: str, contact_email: str) -> Tenant:

    tenant = db.execute(
        select(Tenant).where(func.lower(Tenant.tenant_name) == company_name.strip().lower())
    ).scalar_one_or_none()

    if tenant:
        return tenant

    tenant = Tenant(
        tenant_name=company_name.strip(),
        contact_email=contact_email,
        plan="BASIC",
        status="active",
    )
    db.add(tenant)
    db.flush()  
    return tenant


def _find_tenant(db: Session, company_name: Optional[str]):
    if not company_name or not company_name.strip():
        return None
    return db.execute(
        select(Tenant).where(func.lower(Tenant.tenant_name) == company_name.strip().lower())
    ).scalar_one_or_none()


def _active_branches(db: Session, tenant_id: int):
    return db.execute(
        select(CompanyLocation)
        .where(CompanyLocation.tenant_id == tenant_id, CompanyLocation.is_active.is_(True))
        .order_by(CompanyLocation.is_default.desc(), CompanyLocation.name)
    ).scalars().all()


def _tenant_name(db: Session, tenant_id: Optional[int]) -> Optional[str]:
    if tenant_id is None:
        return None
    tenant = db.get(Tenant, tenant_id)
    return tenant.tenant_name if tenant else None


def _company_profile(db: Session, tenant_id: Optional[int]) -> Optional[CompanyProfile]:
    """The company's profile as edited in Company Settings -> Company Profile (None if not filled in yet)."""
    if tenant_id is None:
        return None
    return (
        db.query(CompanyProfile)
        .filter(CompanyProfile.tenant_id == tenant_id, CompanyProfile.is_deleted.is_(False))
        .first()
    )


def _branch_name(db: Session, location_id: Optional[int]) -> Optional[str]:
    if location_id is None:
        return None
    loc = db.get(CompanyLocation, location_id)
    return loc.name if loc else None


@router.get("/signup-branches")
def signup_branches(company_name: str, db: Session = Depends(get_db)):
    """Public: branches of an existing company, so the signup form can ask which one the
    recruiter works from. Returns [] for an unknown company or one with no branches."""
    tenant = _find_tenant(db, company_name)
    if not tenant:
        return []
    return [
        {"id": b.id, "name": b.name, "city": b.city, "is_default": bool(b.is_default)}
        for b in _active_branches(db, tenant.id)
    ]


@router.post("/signup", status_code=201)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    existing_user = db.execute(
        select(User).where(User.email == payload.email)
    ).scalar_one_or_none()

    if existing_user:
        raise HTTPException(status_code=409, detail="Email already registered")

    # Branch: a recruiter joining a company that has branches must pick one of them.
    existing_tenant = _find_tenant(db, payload.company_name)
    branches = _active_branches(db, existing_tenant.id) if existing_tenant else []
    location_id = None
    if payload.role == "recruiter":
        if branches:
            valid_ids = {b.id for b in branches}
            if payload.location_id is None:
                raise HTTPException(status_code=422, detail="Please select your branch.")
            if payload.location_id not in valid_ids:
                raise HTTPException(status_code=400, detail="That branch does not belong to this company.")
            location_id = payload.location_id
        elif payload.location_id is not None:
            raise HTTPException(status_code=400, detail="That branch does not belong to this company.")

    tenant = get_or_create_tenant(db, payload.company_name, payload.email)

    user = User(
        name=payload.name,
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        role=payload.role,
        company_name=payload.company_name,
        company_website=payload.company_website,
        tenant_id=tenant.id,
        location_id=location_id,
        is_active=False  
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return {"message": "Signup successful. Awaiting admin approval."}


@router.get("/create-superadmin")
def create_superadmin(db: Session = Depends(get_db)):
    existing = db.execute(
        select(User).where(User.email == "superadmin@example.com")
    ).scalar_one_or_none()

    if existing:
        return {"message": "Superadmin already exists"}

    user = User(
        name="Super Admin",
        username="superadmin",
        email="superadmin@example.com",
        hashed_password=get_password_hash("admin123"),
        role="superadmin",
        is_active=True
    )

    db.add(user)
    db.commit()

    return {"message": "Superadmin created successfully"}


@router.post("/login-json", response_model=TokenResponse)
def login_json(payload: LoginJSON, db: Session = Depends(get_db)):
    user = db.execute(
        select(User).where(User.email == payload.email)
    ).scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account not activated by admin")

    token = create_access_token({"sub": str(user.id)})
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "email": user.email,
        "refresh_token": None,
        "requires_password_change": user.requires_password_change,
        "profile_completed": user.profile_completed,
    }

@router.post("/login", response_model=TokenResponse)
def login_form(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = db.execute(
        select(User).where(User.email == form_data.username)
    ).scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account not activated by admin")

    token = create_access_token({"sub": str(user.id)})
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "email": user.email,
        "refresh_token": None,
        "requires_password_change": user.requires_password_change,
        "profile_completed": user.profile_completed,
    }


@router.get("/me", response_model=CurrentUserResponse)
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = _company_profile(db, current_user.tenant_id)
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role,
        "is_active": current_user.is_active,
        "requires_password_change": current_user.requires_password_change,
        "profile_completed": current_user.profile_completed,
        "employee_id": current_user.employee_id,
        "location_id": current_user.location_id,
        "branch_name": _branch_name(db, current_user.location_id),
        "username": current_user.username,
        # One source of truth: the name/website saved in Company Settings -> Company Profile win.
        # Before a profile exists (or if it is blank) fall back to what was typed at signup / the
        # tenant name, exactly as before.
        "company_name": (profile.company_name if profile and profile.company_name else None)
        or current_user.company_name
        or _tenant_name(db, current_user.tenant_id),
        "company_website": (profile.company_website if profile and profile.company_website else None)
        or current_user.company_website,
        "company_id": current_user.company_id,
    }


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Authenticated self-service password change. Used both for the forced
    change after a "Convert to Employee" temporary password, and for any
    user voluntarily changing their password later (requires_password_change
    is simply already False in that case, so it's a no-op to clear).
    """
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")

    current_user.hashed_password = get_password_hash(payload.new_password)
    current_user.requires_password_change = False
    db.add(current_user)
    db.commit()

    return {"message": "Password updated successfully"}



@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.execute(
        select(User).where(User.email == payload.email)
    ).scalar_one_or_none()

   
    if not user:
        return {"message": "If that email exists, a reset link has been sent."}

    token = secrets.token_urlsafe(32)
    _reset_tokens[token] = {"user_id": user.id, "email": user.email}

    reset_link = f"https://hr-ai-levitica.vercel.app/reset-password?token={token}"

    message = MessageSchema(
        subject="Reset your password",
        recipients=[user.email],
        body=f"Click this link to reset your password: {reset_link}\n\nThis link expires in 1 hour.",
        subtype=MessageType.plain,
    )

    try:
        fm = FastMail(mail_config)
        await fm.send_message(message)
    except Exception:
        pass  

    return {"message": "If that email exists, a reset link has been sent."}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    record = _reset_tokens.get(payload.token)
    if not record:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user = db.get(User, record["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = get_password_hash(payload.new_password)
    db.add(user)
    db.commit()

    del _reset_tokens[payload.token]
    return {"message": "Password reset successfully"}