import secrets
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi_mail import FastMail, MessageSchema, MessageType
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.database import get_db
from core.dependencies import get_current_user, require_roles
from core.mail import mail_config
from model.models import OfferStatus, OfferTracking, User
from model.onboarding.candidate import Candidate as OnboardingCandidate
from model.onboarding.employee import GenderEnum
from schema.onboarding.employee import EmployeeCreate
from services.employee_service import create_employee
from routers.admin_users.auth import get_password_hash

router = APIRouter(
    prefix="/api/onboarding-forms/candidates",
    tags=["Onboarding Forms"],
)


# ---------------------------------------------------------------------------
# HR hires candidate -> candidate accepts offer -> candidate completes the
# self-onboarding form (existing invite/approve flow in admin_candidates.py,
# which already gets the Candidate to status "APPROVED") -> THIS endpoint is
# the "Convert to Employee" click: it's the missing link that actually
# provisions the Employee record + login account. Nothing before this point
# creates a User login for the person.
# ---------------------------------------------------------------------------


class ConvertToEmployeeRequest(BaseModel):
    # Everything here is OPTIONAL: if the candidate's self-onboarding form
    # already captured it (via candidate.form_data), that value is used.
    # These are only needed to fill gaps the form didn't collect, or to let
    # HR override something at conversion time (e.g. assign a department).
    joining_date: Optional[date] = None
    gender: Optional[GenderEnum] = None
    mobile_number: Optional[str] = None
    official_email: Optional[EmailStr] = None
    designation: Optional[str] = None
    department: Optional[str] = None
    business_unit: Optional[str] = None
    location_id: Optional[int] = None
    grade: Optional[str] = None
    cost_center: Optional[str] = None
    reporting_manager_id: Optional[int] = None


class ConvertToEmployeeResponse(BaseModel):
    employee_id: int
    employee_code: str
    user_id: int
    login_email: str
    # Only returned so HR has a fallback way to hand over credentials if the
    # email below fails to send (e.g. SMTP not configured in this
    # environment) — it is never logged and never stored anywhere.
    temporary_password: str
    email_sent: bool


def _split_name(full_name: str) -> tuple[str, Optional[str]]:
    parts = full_name.strip().split(None, 1)
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1]


def _generate_temp_password() -> str:
    # Short, readable-ish, but still high-entropy: 12 URL-safe chars.
    return secrets.token_urlsafe(9)


async def _send_credentials_email(
    to_email: str, name: str, employee_code: str, login_email: str, temp_password: str
) -> bool:
    html_body = f"""
    <div style="font-family:Arial,sans-serif;line-height:1.6;color:#333;">
        <p>Hello <b>{name}</b>,</p>
        <p>Welcome aboard! Your employee account has been created.</p>
        <table style="margin:12px 0;border-collapse:collapse;">
            <tr><td style="padding:4px 12px 4px 0;color:#666;">Employee ID</td><td><b>{employee_code}</b></td></tr>
            <tr><td style="padding:4px 12px 4px 0;color:#666;">Login Email</td><td><b>{login_email}</b></td></tr>
            <tr><td style="padding:4px 12px 4px 0;color:#666;">Temporary Password</td><td><b>{temp_password}</b></td></tr>
        </table>
        <p>Please log in and set your own password before doing anything else — you'll
        be asked to change it automatically on first login.</p>
        <br/>
        <p>Best Regards,<br/><b>Human Resources</b></p>
    </div>
    """
    message = MessageSchema(
        subject="Your Employee Account Is Ready",
        recipients=[to_email],
        body=html_body,
        subtype=MessageType.html,
    )
    await FastMail(mail_config).send_message(message)
    return True


@router.post(
    "/{candidate_id}/convert-to-employee",
    response_model=ConvertToEmployeeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Convert an approved onboarding candidate into an Employee + login account",
)
async def convert_to_employee(
    candidate_id: int,
    payload: ConvertToEmployeeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["hr_admin", "admin", "company", "superadmin"])),
):
    candidate = db.query(OnboardingCandidate).filter(OnboardingCandidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Onboarding candidate not found")

    if candidate.status != "APPROVED":
        raise HTTPException(
            status_code=400,
            detail=f"Candidate must be APPROVED before conversion (current status: '{candidate.status}').",
        )

    # A candidate can only be converted once — the resulting User.email is
    # unique anyway, but check up front for a clean error message instead of
    # a raw DB conflict.
    already_converted = db.execute(
        select(User).where(User.email == candidate.email)
    ).scalar_one_or_none()
    if already_converted is not None:
        raise HTTPException(
            status_code=409,
            detail="This candidate already has an employee login account.",
        )

    form_data = candidate.form_data or {}
    first_name, last_name = _split_name(candidate.full_name)

    # Details already agreed in the accepted offer (position / department) are
    # used when HR does not override them, so nothing has to be retyped.
    offer = None
    if candidate.email:
        offer = (
            db.query(OfferTracking)
            .filter(func.lower(OfferTracking.candidate_email) == candidate.email.strip().lower())
            .filter(OfferTracking.status == OfferStatus.accepted)
            .order_by(OfferTracking.id.desc())
            .first()
        )

    gender = payload.gender or form_data.get("gender")
    mobile_number = payload.mobile_number or candidate.mobile or form_data.get("mobile_number")
    joining_date = payload.joining_date or date.today()

    missing = [
        name
        for name, val in (("gender", gender), ("mobile_number", mobile_number))
        if not val
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot convert: missing required field(s) "
                f"{', '.join(missing)}. The onboarding form didn't collect "
                "these, so pass them in the request body."
            ),
        )

    employee_payload = EmployeeCreate(
        first_name=first_name,
        last_name=last_name,
        joining_date=joining_date,
        gender=gender,
        mobile_number=mobile_number,
        personal_email=candidate.email,
        official_email=payload.official_email,
        designation=payload.designation or (offer.position if offer else None),
        department=payload.department or (offer.department if offer else None),
        business_unit=payload.business_unit,
        location_id=payload.location_id,
        grade=payload.grade,
        cost_center=payload.cost_center,
        reporting_manager_id=payload.reporting_manager_id,
    )
    employee = create_employee(db, employee_payload)
    # Tenant-scope the new Employee to match whoever performed the
    # conversion, so it shows up correctly in that company's branch/tenant
    # filtered views (create_employee itself doesn't know about tenants).
    employee.tenant_id = current_user.tenant_id
    db.add(employee)
    db.commit()
    db.refresh(employee)

    login_email = employee.official_email or employee.personal_email or candidate.email
    if not login_email:
        raise HTTPException(
            status_code=400,
            detail="Cannot create a login: no official email, personal email, or candidate email available.",
        )

    temp_password = _generate_temp_password()
    user = User(
        name=candidate.full_name,
        email=login_email,
        hashed_password=get_password_hash(temp_password),
        role="employee",
        is_active=True,
        tenant_id=current_user.tenant_id,
        location_id=employee.location_id,
        employee_id=employee.id,
        requires_password_change=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    candidate.status = "CONVERTED"
    db.commit()

    email_sent = False
    try:
        email_sent = await _send_credentials_email(
            to_email=login_email,
            name=candidate.full_name,
            employee_code=employee.employee_code,
            login_email=login_email,
            temp_password=temp_password,
        )
    except Exception as exc:
        # Same defensive pattern as invite_candidate() in admin_candidates.py
        # — a mail failure shouldn't roll back an otherwise-successful
        # conversion. HR can hand over temporary_password from the response
        # instead.
        print("❌ Credentials email failed:", exc)

    return ConvertToEmployeeResponse(
        employee_id=employee.id,
        employee_code=employee.employee_code,
        user_id=user.id,
        login_email=login_email,
        temporary_password=temp_password,
        email_sent=email_sent,
    )