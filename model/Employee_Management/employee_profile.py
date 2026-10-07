from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Date, DateTime, Boolean,
    Numeric, Text, ForeignKey, JSON
)
from sqlalchemy.orm import relationship
from core.database import Base



class EmployeePersonalInfo(Base):
    __tablename__ = "employee_personal_info"

    id            = Column(Integer, primary_key=True, index=True)
    employee_id   = Column(Integer, ForeignKey("employees.id"), unique=True, nullable=False, index=True)

    
    date_of_birth  = Column(Date, nullable=True)
    gender         = Column(String(50), nullable=True)
    blood_group    = Column(String(10), nullable=True)
    marital_status = Column(String(50), nullable=True)
    nationality    = Column(String(100), nullable=True)
    languages      = Column(JSON, nullable=True, default=list)   # ["English","Hindi"]
    profile_photo  = Column(Text, nullable=True)                 # base64 data-URL

 
    personal_email   = Column(String(255), nullable=True)
    phone_primary    = Column(String(15), nullable=True)
    phone_secondary  = Column(String(15), nullable=True)
    phone_emergency  = Column(String(15), nullable=True)

   
    curr_line1   = Column(String(255), nullable=True)
    curr_line2   = Column(String(255), nullable=True)
    curr_city    = Column(String(100), nullable=True)
    curr_state   = Column(String(100), nullable=True)
    curr_pincode = Column(String(20),  nullable=True)
    curr_country = Column(String(100), nullable=True)


    perm_line1   = Column(String(255), nullable=True)
    perm_line2   = Column(String(255), nullable=True)
    perm_city    = Column(String(100), nullable=True)
    perm_state   = Column(String(100), nullable=True)
    perm_pincode = Column(String(20),  nullable=True)
    perm_country = Column(String(100), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmployeeEmergencyContact(Base):
    __tablename__ = "employee_emergency_contacts"
    __table_args__ = {"extend_existing": True}

    id          = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    name        = Column(String(150), nullable=False)
    relation    = Column(String(100), nullable=True)
    phone       = Column(String(15),  nullable=True)
    priority    = Column(String(50),  nullable=True, default="Primary")  # Primary/Secondary/Tertiary


class EmployeeFamilyMember(Base):
    __tablename__ = "employee_family_members"

    id          = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    name        = Column(String(150), nullable=False)
    relation    = Column(String(100), nullable=True)
    date_of_birth = Column(Date, nullable=True)
    contact_no  = Column(String(15),  nullable=True)


class EmployeeNominee(Base):
    __tablename__ = "employee_nominees"

    id                  = Column(Integer, primary_key=True, index=True)
    employee_id         = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    name                = Column(String(150), nullable=False)
    relation            = Column(String(100), nullable=True)
    phone               = Column(String(15),  nullable=True)
    percentage          = Column(Integer,     nullable=True, default=0)
    is_nominee_accepted = Column(Boolean,     nullable=True, default=False)


class EmployeeIdentification(Base):
    __tablename__ = "employee_identification"

    id          = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), unique=True, nullable=False, index=True)

    
    pan_number   = Column(String(20),  nullable=True)
    pan_verified = Column(Boolean,     nullable=True, default=False)

    
    aadhaar_number   = Column(String(20), nullable=True)
    aadhaar_verified = Column(Boolean,    nullable=True, default=False)

   
    passport_number      = Column(String(30), nullable=True)
    passport_expiry_date = Column(Date,       nullable=True)
    passport_verified    = Column(Boolean,    nullable=True, default=False)

  
    voter_id_number   = Column(String(30), nullable=True)
    voter_id_verified = Column(Boolean,    nullable=True, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmployeeEmploymentInfo(Base):
    __tablename__ = "employee_employment_info"

    id          = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), unique=True, nullable=False, index=True)

    employee_code      = Column(String(50),  nullable=True)  
    date_of_joining    = Column(Date,        nullable=True)
    confirmation_date  = Column(Date,        nullable=True)
    probation_period   = Column(Integer,     nullable=True, default=6)  
    employment_type    = Column(String(100), nullable=True, default="Permanent")
    employment_status  = Column(String(100), nullable=True, default="Active")
    department         = Column(String(150), nullable=True)
    sub_department     = Column(String(150), nullable=True)
    cost_center        = Column(String(100), nullable=True)
    designation        = Column(String(150), nullable=True)
    grade              = Column(String(50),  nullable=True)
    level              = Column(String(50),  nullable=True)  
    location           = Column(String(200), nullable=True)  # legacy free-text, kept for backward compatibility
    location_id        = Column(Integer, ForeignKey("company_locations.id"), nullable=True, index=True)  # branch
    workplace_type     = Column(String(50),  nullable=True)   
    work_email         = Column(String(255), nullable=True)
    extension_number   = Column(String(20),  nullable=True)
    desk_location      = Column(String(100), nullable=True)
    employee_category  = Column(String(100), nullable=True)   
    notice_period      = Column(Integer,     nullable=True, default=30) 
    direct_manager     = Column(String(200), nullable=True)

    branch = relationship("CompanyLocation", foreign_keys=[location_id])
    functional_manager = Column(String(200), nullable=True)
    hr_business_partner = Column(String(200), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmployeeJobHistory(Base):
    __tablename__ = "employee_job_history"

    id          = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)

    start_date       = Column(Date,        nullable=True)
    end_date         = Column(String(50),  nullable=True)   
    history_type     = Column(String(100), nullable=True)  
    organisation     = Column(String(200), nullable=True)
    department       = Column(String(150), nullable=True)
    designation      = Column(String(150), nullable=True)
    location         = Column(String(200), nullable=True)
    manager          = Column(String(200), nullable=True)
    salary_change    = Column(Numeric(15, 2), nullable=True)
    notes            = Column(Text,        nullable=True)
    achievements     = Column(Text,        nullable=True)
    reason_for_leaving = Column(Text,      nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)



class EmployeeSalaryInfo(Base):
    __tablename__ = "employee_salary_info"

    id          = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), unique=True, nullable=False, index=True)

    current_ctc        = Column(Numeric(15, 2), nullable=True, default=0)
    salary_structure   = Column(String(100),    nullable=True)   

 
    basic                = Column(Numeric(15, 2), nullable=True, default=0)
    hra                  = Column(Numeric(15, 2), nullable=True, default=0)
    special_allowance    = Column(Numeric(15, 2), nullable=True, default=0)
    transport_allowance  = Column(Numeric(15, 2), nullable=True, default=0)
    medical_allowance    = Column(Numeric(15, 2), nullable=True, default=0)
    other_allowances     = Column(Numeric(15, 2), nullable=True, default=0)
    provident_fund       = Column(Numeric(15, 2), nullable=True, default=0)
    gratuity             = Column(Numeric(15, 2), nullable=True, default=0)
    other_deductions     = Column(Numeric(15, 2), nullable=True, default=0)

    payment_mode         = Column(String(50),  nullable=True, default="Bank Transfer")
    pf_account_number    = Column(String(50),  nullable=True)
    uan                  = Column(String(20),  nullable=True)
    esi_number           = Column(String(20),  nullable=True)
    esi_medical_nominee  = Column(String(200), nullable=True)

    tax_regime           = Column(String(50),  nullable=True, default="New")
    tax_declared         = Column(Boolean,     nullable=True, default=False)
    variable_pay_eligible = Column(Boolean,    nullable=True, default=False)
    variable_pay_pct     = Column(Numeric(5, 2), nullable=True, default=0)
    bonus_eligible       = Column(Boolean,     nullable=True, default=False)
    bonus_amount         = Column(Numeric(15, 2), nullable=True, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmployeeBankAccount(Base):
    __tablename__ = "employee_bank_accounts"

    id             = Column(Integer, primary_key=True, index=True)
    employee_id    = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    account_type_label = Column(String(20), nullable=True, default="primary")  

    account_number = Column(String(30),  nullable=True)
    ifsc_code      = Column(String(20),  nullable=True)
    bank_name      = Column(String(200), nullable=True)
    branch         = Column(String(200), nullable=True)
    account_type   = Column(String(50),  nullable=True, default="Savings")  

    created_at = Column(DateTime, default=datetime.utcnow)


class EmployeeSalaryRevision(Base):
    __tablename__ = "employee_salary_revisions"

    id          = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)

    effective_date     = Column(Date,       nullable=True)
    previous_ctc       = Column(Numeric(15, 2), nullable=True, default=0)
    new_ctc            = Column(Numeric(15, 2), nullable=True, default=0)
    percentage_increase = Column(Numeric(5, 2),  nullable=True, default=0)
    approved_by        = Column(String(200), nullable=True)
    status             = Column(String(50),  nullable=True, default="Pending")  

    created_at = Column(DateTime, default=datetime.utcnow)


class EmployeeStatutoryInfo(Base):
    __tablename__ = "employee_statutory_info"

    id          = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), unique=True, nullable=False, index=True)

  
    pan_number        = Column(String(20),  nullable=True)
    pan_verified      = Column(Boolean,     nullable=True, default=False)
    pan_verified_date = Column(Date,        nullable=True)

 
    aadhaar_number        = Column(String(20), nullable=True)
    aadhaar_verified      = Column(Boolean,    nullable=True, default=False)
    aadhaar_verified_date = Column(Date,       nullable=True)


    pf_enrolled        = Column(Boolean,    nullable=True, default=False)
    pf_account_number  = Column(String(50), nullable=True)
    pf_uan             = Column(String(20), nullable=True)
    pf_enrollment_date = Column(Date,       nullable=True)
    pf_account_type    = Column(String(50), nullable=True)   

    esi_enrolled        = Column(Boolean,    nullable=True, default=False)
    esi_number          = Column(String(20), nullable=True)
    esi_enrollment_date = Column(Date,       nullable=True)

    pt_applicable = Column(Boolean,     nullable=True, default=False)
    pt_state      = Column(String(100), nullable=True)
    pt_number     = Column(String(20),  nullable=True)
    lwf_enrolled        = Column(Boolean, nullable=True, default=False)
    lwf_enrollment_date = Column(Date,    nullable=True)

    gratuity_eligible        = Column(Boolean, nullable=True, default=False)
    gratuity_eligibility_date = Column(Date,   nullable=True)

    bonus_act_applicable = Column(Boolean, nullable=True, default=False)

    shops_registered         = Column(Boolean,     nullable=True, default=False)
    shops_registration_number = Column(String(50), nullable=True)
    shops_registration_date   = Column(Date,       nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)