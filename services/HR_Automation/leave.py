from sqlalchemy.orm import Session
from sqlalchemy import select, or_, func
from fastapi import HTTPException
from typing import Optional
from datetime import datetime

from model.models import LeaveRequest, LeaveStatus
from model.onboarding.employee import Employee
from schema.HR_Automation.leave import LeaveRequestCreate, LeaveRequestUpdate



LEAVE_TYPE_NAMES = {
    "CL": "Casual Leave",
    "SL": "Sick Leave",
    "EL": "Earned Leave",
    "ML": "Maternity Leave",
    "PL": "Paternity Leave",
    "BL": "Bereavement Leave",
}


def _parse_status(value: str) -> LeaveStatus:
    """Accept 'Pending', 'pending', 'PENDING' (value or member name)."""
    key = (value or "").strip().lower()
    for member in LeaveStatus:
        if key in (member.value.lower(), member.name.lower()):
            return member
    raise HTTPException(
        status_code=400,
        detail=f"Invalid status '{value}'. Must be one of: {[s.value for s in LeaveStatus]}",
    )


def _calc_days(start_date, end_date, is_half_day: bool) -> float:
    total = (end_date - start_date).days + 1
    if is_half_day and total == 1:
        return 0.5
    return float(total)


def _to_out_dict(leave: LeaveRequest, employee_map: dict) -> dict:
    emp = employee_map.get(leave.employee_id)
    approver = employee_map.get(leave.approved_by) if leave.approved_by else None
    return {
        "id": leave.id,
        "employee_id": leave.employee_id,
        "employee_name": f"{emp.first_name} {emp.last_name or ''}".strip() if emp else "Unknown",
        "leave_type": LEAVE_TYPE_NAMES.get(leave.leave_type, leave.leave_type),
        "leave_type_code": leave.leave_type,
        "start_date": leave.start_date,
        "end_date": leave.end_date,
        "days": _calc_days(leave.start_date, leave.end_date, leave.is_half_day),
        "is_half_day": leave.is_half_day,
        "reason": leave.reason,
        "status": leave.status.value if hasattr(leave.status, "value") else leave.status,
        "approved_by": leave.approved_by,
        "approved_by_name": f"{approver.first_name} {approver.last_name or ''}".strip() if approver else None,
        "rejection_reason": leave.rejection_reason,
        "applied_at": leave.applied_at,
    }


def _employee_map_for(db: Session, leaves: list) -> dict:
    emp_ids = {l.employee_id for l in leaves} | {l.approved_by for l in leaves if l.approved_by}
    if not emp_ids:
        return {}
    rows = db.execute(select(Employee).where(Employee.id.in_(emp_ids))).scalars().all()
    return {e.id: e for e in rows}


def create_leave(db: Session, payload: LeaveRequestCreate) -> dict:
    emp = db.execute(
        select(Employee).where(Employee.id == payload.employee_id)
    ).scalar_one_or_none()
    if not emp:
        raise HTTPException(status_code=404, detail=f"Employee {payload.employee_id} not found")

    leave = LeaveRequest(
        employee_id=payload.employee_id,
        leave_type=payload.leave_type,
        start_date=payload.start_date,
        end_date=payload.end_date,
        is_half_day=payload.is_half_day or False,
        reason=payload.reason,
        status=LeaveStatus.pending,
    )
    db.add(leave)
    db.commit()
    db.refresh(leave)

    return _to_out_dict(leave, {emp.id: emp})


def list_applications(
    db: Session,
    search: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    
    stmt = select(LeaveRequest)

    if status and status not in ("All Status", "All", ""):
        stmt = stmt.where(LeaveRequest.status == _parse_status(status))

    leaves = db.execute(stmt.order_by(LeaveRequest.applied_at.desc())).scalars().all()
    employee_map = _employee_map_for(db, leaves)

    results = [_to_out_dict(l, employee_map) for l in leaves]

    if search:
        s = search.strip().lower()
        results = [
            r for r in results
            if s in r["employee_name"].lower()
            or s in r["leave_type"].lower()
            or s in (r["reason"] or "").lower()
        ]

    return {"applications": results, "total": len(results)}


def get_leave(db: Session, leave_id: int) -> dict:
    leave = db.execute(
        select(LeaveRequest).where(LeaveRequest.id == leave_id)
    ).scalar_one_or_none()
    if not leave:
        raise HTTPException(status_code=404, detail="Leave application not found")

    employee_map = _employee_map_for(db, [leave])
    return _to_out_dict(leave, employee_map)


def update_leave_status(db: Session, leave_id: int, payload: LeaveRequestUpdate) -> dict:
    
    leave = db.execute(
        select(LeaveRequest).where(LeaveRequest.id == leave_id)
    ).scalar_one_or_none()
    if not leave:
        raise HTTPException(status_code=404, detail="Leave application not found")

    if payload.status:
        leave.status = _parse_status(payload.status)

    if payload.approved_by is not None:
        leave.approved_by = payload.approved_by

    if payload.rejection_reason is not None:
        leave.rejection_reason = payload.rejection_reason

    leave.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(leave)

    employee_map = _employee_map_for(db, [leave])
    return _to_out_dict(leave, employee_map)


def delete_leave(db: Session, leave_id: int) -> dict:
    leave = db.execute(
        select(LeaveRequest).where(LeaveRequest.id == leave_id)
    ).scalar_one_or_none()
    if not leave:
        raise HTTPException(status_code=404, detail="Leave application not found")
    db.delete(leave)
    db.commit()
    return {"message": "Leave application deleted successfully"}
