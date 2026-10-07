
from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import date
 
 
class LeaveReportStats(BaseModel):
    total_employees: int
    avg_age: float
    total_leaves: int
    pending: int
    approved: int
    rejected: int
 
 
class LeaveBalanceItem(BaseModel):
    employee_name: str
    employee_id: str
    department: Optional[str]
    grade: Optional[str]
    designation: Optional[str]
    casual_leave_used: int
    casual_leave_balance: int
    casual_leave_total: int
    sick_leave_used: int
    sick_leave_balance: int
    sick_leave_total: int
    earned_leave_used: int
    earned_leave_balance: int
    earned_leave_total: int
    total_balance: int
 
 
class DeptLeaveLiabilityItem(BaseModel):
    department: str
    employees: int
    total_balance_days: int
    encashment_liability: float
 
 
class LeaveTypeUtilizationItem(BaseModel):
    department: str
    total_leaves_taken: int
 
 
class LeaveAccrualItem(BaseModel):
    employee_name: str
    employee_id: str
    department: Optional[str]
    grade: Optional[str]
    accrual_date: date
    leave_type: str
    days_accrued: float
    balance_before: float
    balance_after: float
 
 
class CarryForwardItem(BaseModel):
    employee_name: str
    employee_id: str
    department: Optional[str]
    grade: Optional[str]
    leave_type: str
    previous_year_balance: int
    carried_forward: int
    current_year_allocated: int
    total_available: int
 
 
class LeaveEncashmentItem(BaseModel):
    department: str
    employees: int
    total_balance_days: int
    encashment_liability: float
 
 
class EmployeeLeaveRecordItem(BaseModel):
    id: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    email: Optional[str] = None
    date_of_birth: Optional[date] = None
    employee_code: str
    employee_name: str
    department: Optional[str]
    grade: Optional[str]
    designation: Optional[str]
    location: Optional[str]
    gender: Optional[str]
    mobile: Optional[str]
    leave_type: str
    status: str