from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func, extract
from typing import List, Optional
from datetime import date
 
from core.database import get_db
from core.dependencies import get_current_user
from model.models import User, LeaveRequest, LeaveStatus
from model.onboarding.employee import Employee
 
from schema.Reports.leave_reports import (
    LeaveReportStats,
    LeaveBalanceItem,
    DeptLeaveLiabilityItem,
    LeaveTypeUtilizationItem,
    LeaveAccrualItem,
    CarryForwardItem,
    LeaveEncashmentItem,
    EmployeeLeaveRecordItem,
)
 
router = APIRouter(prefix="/leave", tags=["Leave Reports"])
 
CASUAL_TOTAL  = 12
SICK_TOTAL    = 10
EARNED_TOTAL  = 15
ACCRUAL_RATE  = 1.25  
DAILY_RATE    = 2000     


def _leave_days(leave) -> float:
    days = (leave.end_date - leave.start_date).days + 1
    return 0.5 if getattr(leave, "is_half_day", False) and days == 1 else float(days)


def _type_key(leave_type: Optional[str]) -> Optional[str]:
    """Map the different spellings the app stores (CL, Casual Leave, CASUAL...) to one key."""
    t = (leave_type or "").strip().lower()
    if t in ("cl", "casual", "casual leave"):
        return "casual"
    if t in ("sl", "sick", "sick leave"):
        return "sick"
    if t in ("el", "earned", "earned leave", "pl", "privilege leave"):
        return "earned"
    return None


def _status_member(value: str) -> LeaveStatus:
    key = (value or "").strip().lower()
    for m in LeaveStatus:
        if key in (m.value.lower(), m.name.lower()):
            return m
    raise HTTPException(status_code=400, detail=f"Invalid status '{value}'")
 

 
@router.get("/stats", response_model=LeaveReportStats)
def get_leave_stats(
    department: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    grade: Optional[str] = Query(None),
    gender: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    
    emp_stmt = select(Employee).where(Employee.is_active == True)
    if department:
        emp_stmt = emp_stmt.where(Employee.department == department)
    if location:
        emp_stmt = emp_stmt.where(Employee.location == location)
    if grade:
        emp_stmt = emp_stmt.where(Employee.grade == grade)
    if gender:
        emp_stmt = emp_stmt.where(Employee.gender == gender)
 
    employees = db.execute(emp_stmt).scalars().all()
    total_employees = len(employees)
 
    from datetime import datetime
    avg_age = 0.0
    if employees:
        ages = [
            (datetime.today().date() - emp.date_of_birth).days // 365
            for emp in employees if emp.date_of_birth
        ]
        avg_age = round(sum(ages) / len(ages), 1) if ages else 0.0
 
    total_leaves = db.execute(select(func.count()).select_from(LeaveRequest)).scalar_one()
    pending  = db.execute(select(func.count()).select_from(LeaveRequest).where(LeaveRequest.status == "pending")).scalar_one()
    approved = db.execute(select(func.count()).select_from(LeaveRequest).where(LeaveRequest.status == "approved")).scalar_one()
    rejected = db.execute(select(func.count()).select_from(LeaveRequest).where(LeaveRequest.status == "rejected")).scalar_one()
 
    return LeaveReportStats(
        total_employees=total_employees,
        avg_age=avg_age,
        total_leaves=total_leaves,
        pending=pending,
        approved=approved,
        rejected=rejected,
    )
 

 
@router.get("/balance", response_model=List[LeaveBalanceItem])
def get_employee_leave_balance(
    department: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    grade: Optional[str] = Query(None),
    gender: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    
    stmt = select(Employee).where(Employee.is_active == True)
    if department:
        stmt = stmt.where(Employee.department == department)
    if location:
        stmt = stmt.where(Employee.location == location)
    if grade:
        stmt = stmt.where(Employee.grade == grade)
    if gender:
        stmt = stmt.where(Employee.gender == gender)
    if search:
        stmt = stmt.where(
            (Employee.first_name.ilike(f"%{search}%")) |
            (Employee.last_name.ilike(f"%{search}%")) |
            (Employee.employee_code.ilike(f"%{search}%"))
        )
 
    employees = db.execute(stmt).scalars().all()
    result = []

    # Approved leave days per employee and leave type (one query, not one per employee).
    used_days: dict = {}
    approved = db.execute(
        select(LeaveRequest).where(LeaveRequest.status == LeaveStatus.approved)
    ).scalars().all()
    for lv in approved:
        key = _type_key(lv.leave_type)
        if key and lv.employee_id is not None:
            used_days[(lv.employee_id, key)] = used_days.get((lv.employee_id, key), 0.0) + _leave_days(lv)

    for emp in employees:
        casual_used = int(round(used_days.get((emp.id, "casual"), 0)))
        sick_used   = int(round(used_days.get((emp.id, "sick"), 0)))
        earned_used = int(round(used_days.get((emp.id, "earned"), 0)))
 
        result.append(LeaveBalanceItem(
            employee_name=f"{emp.first_name} {emp.last_name or ''}".strip(),
            employee_id=emp.employee_code,
            department=emp.department,
            grade=emp.grade,
            designation=emp.designation,
            casual_leave_used=casual_used,
            casual_leave_balance=max(CASUAL_TOTAL - casual_used, 0),
            casual_leave_total=CASUAL_TOTAL,
            sick_leave_used=sick_used,
            sick_leave_balance=max(SICK_TOTAL - sick_used, 0),
            sick_leave_total=SICK_TOTAL,
            earned_leave_used=earned_used,
            earned_leave_balance=max(EARNED_TOTAL - earned_used, 0),
            earned_leave_total=EARNED_TOTAL,
            total_balance=max(CASUAL_TOTAL - casual_used, 0) + max(SICK_TOTAL - sick_used, 0) + max(EARNED_TOTAL - earned_used, 0),
        ))
 
    return result
 
 
 
@router.get("/dept-liability", response_model=List[DeptLeaveLiabilityItem])
def get_dept_leave_liability(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    
    results = db.execute(
        select(
            Employee.department,
            func.count(Employee.id).label("emp_count"),
        )
        .where(Employee.is_active == True)
        .group_by(Employee.department)
    ).all()
 
    items = []
    for r in results:
        total_balance = r.emp_count * (CASUAL_TOTAL + SICK_TOTAL + EARNED_TOTAL)
        encashment = total_balance * DAILY_RATE
        items.append(DeptLeaveLiabilityItem(
            department=r.department or "Unknown",
            employees=r.emp_count,
            total_balance_days=total_balance,
            encashment_liability=encashment,
        ))
    return items
 
 
 
@router.get("/utilization", response_model=List[LeaveTypeUtilizationItem])
def get_leave_utilization(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    results = db.execute(
        select(
            Employee.department,
            func.count(LeaveRequest.id).label("total_leaves"),
        )
        .join(LeaveRequest, LeaveRequest.leave_type != None, isouter=True)
        .where(Employee.is_active == True)
        .group_by(Employee.department)
    ).all()
 
    return [
        LeaveTypeUtilizationItem(
            department=r.department or "Unknown",
            total_leaves_taken=r.total_leaves or 0,
        )
        for r in results
    ]
 
 

 
@router.get("/accrual", response_model=List[LeaveAccrualItem])
def get_leave_accrual_register(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    employees = db.execute(
        select(Employee).where(Employee.is_active == True)
    ).scalars().all()
 
    result = []
    accrual_date = date(2024, 1, 1)
 
    for emp in employees:
        
        joining = emp.joining_date
        months = max(
            (accrual_date.year - joining.year) * 12 + (accrual_date.month - joining.month),
            0
        )
        balance_before = round(months * ACCRUAL_RATE, 2)
        balance_after  = round(balance_before + ACCRUAL_RATE, 2)
 
        result.append(LeaveAccrualItem(
            employee_name=f"{emp.first_name} {emp.last_name or ''}".strip(),
            employee_id=emp.employee_code,
            department=emp.department,
            grade=emp.grade,
            accrual_date=accrual_date,
            leave_type="Earned Leave",
            days_accrued=ACCRUAL_RATE,
            balance_before=balance_before,
            balance_after=balance_after,
        ))
 
    return result
 
 
 
@router.get("/carry-forward", response_model=List[CarryForwardItem])
def get_carry_forward_tracking(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    employees = db.execute(
        select(Employee).where(Employee.is_active == True)
    ).scalars().all()
 
    result = []
    for emp in employees:
        for leave_type, prev_bal, cf, allocated in [
            ("Casual Leave", 2,  2,  12),
            ("Earned Leave", 5,  5,  15),
        ]:
            result.append(CarryForwardItem(
                employee_name=f"{emp.first_name} {emp.last_name or ''}".strip(),
                employee_id=emp.employee_code,
                department=emp.department,
                grade=emp.grade,
                leave_type=leave_type,
                previous_year_balance=prev_bal,
                carried_forward=cf,
                current_year_allocated=allocated,
                total_available=cf + allocated,
            ))
 
    return result
 

 
@router.get("/encashment", response_model=List[LeaveEncashmentItem])
def get_leave_encashment_liability(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    results = db.execute(
        select(
            Employee.department,
            func.count(Employee.id).label("emp_count"),
        )
        .where(Employee.is_active == True)
        .group_by(Employee.department)
    ).all()
 
    return [
        LeaveEncashmentItem(
            department=r.department or "Unknown",
            employees=r.emp_count,
            total_balance_days=r.emp_count * EARNED_TOTAL,
            encashment_liability=r.emp_count * EARNED_TOTAL * DAILY_RATE,
        )
        for r in results
    ]
 
 
 
@router.get("/records", response_model=List[EmployeeLeaveRecordItem])
def get_employee_leave_records(
    department: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="pending | approved | rejected"),
    leave_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    emp_stmt = select(Employee).where(Employee.is_active == True)
    if department:
        emp_stmt = emp_stmt.where(Employee.department == department)
    employees = db.execute(emp_stmt).scalars().all()
    emp_map = {emp.id: emp for emp in employees}
 
    leave_stmt = select(LeaveRequest)
    if status:
        leave_stmt = leave_stmt.where(LeaveRequest.status == _status_member(status))
    if leave_type:
        leave_stmt = leave_stmt.where(LeaveRequest.leave_type == leave_type)
    leaves = db.execute(leave_stmt).scalars().all()
 
    result = []
    for leave in leaves:
        emp = emp_map.get(leave.employee_id)
        if not emp:
            continue
        result.append(EmployeeLeaveRecordItem(
            id=leave.id,
            start_date=leave.start_date,
            end_date=leave.end_date,
            email=emp.official_email,
            date_of_birth=emp.date_of_birth,
            employee_code=emp.employee_code,
            employee_name=f"{emp.first_name} {emp.last_name or ''}".strip(),
            department=emp.department,
            grade=emp.grade,
            designation=emp.designation,
            location=emp.location,
            gender=emp.gender.value if emp.gender else None,
            mobile=emp.mobile_number,
            leave_type=leave.leave_type,
            status=leave.status.value if hasattr(leave.status, 'value') else str(leave.status),
        ))
 
    return result