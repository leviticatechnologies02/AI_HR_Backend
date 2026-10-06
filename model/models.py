import os
import enum
from datetime import datetime, date
from typing import Optional, List

from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, Integer, String, Text, Date, ForeignKey, JSON as SA_JSON, Enum as SAEnum,Float, DateTime,Boolean
from sqlalchemy.orm import relationship
from core.database import Base, engine



class Role(str, enum.Enum):
    recruiter = "recruiter"
    company = "company"
    admin = "admin"

class ApplicationStatus(str, enum.Enum):
    applied = "applied"
    pipeline = "pipeline"
    rejected = "rejected"
    hired = "hired"

class LeaveStatus(str, enum.Enum):
    pending = "Pending"
    approved = "Approved"
    rejected = "Rejected"

class DocStatus(str, enum.Enum):
    pending = "Pending"
    uploaded = "Uploaded"


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    username: Optional[str] = None
    email: str
    hashed_password: str
    role: str
    is_active: bool = Field(default=False)
    company_name: Optional[str]
    company_website: Optional[str]
    company_id: Optional[str] = None
    # Required by the Company Settings routers (current_user.tenant_id) —
    # those endpoints would throw AttributeError without this. References
    # super_admin.multi_tenant.Tenant.id conceptually (cross-Base FK, so no
    # hard `foreign_key=` constraint to avoid SQLModel/SQLAlchemy metadata
    # ordering issues between the two declarative bases in this codebase).
    tenant_id: Optional[int] = None
    # Branch-level scoping for "admin" role: when set, an admin's access is
    # narrowed to just this branch (see get_current_location_id in
    # core/dependencies.py) instead of the whole tenant. References
    # CompanyLocation.id conceptually — same cross-Base soft-FK reasoning as
    # tenant_id above (no hard `foreign_key=`, different declarative Base).
    # None means "not branch-restricted" (whole-tenant access, or role is
    # not admin/hr_admin at all — e.g. superadmin, recruiter, company).
    location_id: Optional[int] = None
    # Soft reference to Employee.id (model/onboarding/employee.py — a
    # different declarative Base, same cross-Base reasoning as tenant_id/
    # location_id above: no hard `foreign_key=`). Set when this login was
    # created via "Convert to Employee"; None for logins that aren't an
    # employee self-service account (company/admin/hr_admin/recruiter/
    # superadmin/candidate).
    employee_id: Optional[int] = None
    # True right after "Convert to Employee" creates a temporary password.
    # The employee must set their own password before using the rest of
    # the HRMS — enforced by the frontend redirecting on this flag and by
    # POST /api/auth/change-password clearing it.
    requires_password_change: bool = Field(default=False)
    # True once the employee has completed bank details + emergency contact
    # + at least one document upload after their first login. Mirrors
    # requires_password_change: the frontend gates the full self-service
    # dashboard behind this the same way it gates behind the forced
    # password change, matching "Account becomes active" in the hiring
    # flow. HR/admin/etc. logins are simply never checked against this.
    profile_completed: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    department: str
    employment_type: str
    location: Optional[str]
    is_remote: bool = False
    description: str
    responsibilities: Optional[str] = None
    requirements: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    currency: str = "USD"
    benefits: List[str] = Field(default_factory=list, sa_column=Column(SA_JSON))
    skills: List[str] = Field(default_factory=list, sa_column=Column(SA_JSON))
    expiry_date: Optional[date] = None
    reference_id: Optional[str] = None
    jd_file: Optional[str] = None
    status: str = "Draft"
    role: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    recruiter_id: int = Field(foreign_key="user.id")
    recruiter: Optional["User"] = Relationship()
    applications: List["Application"] = Relationship(back_populates="job")

class Candidate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str
    hashed_password: Optional[str] = None 
    role: str
    skills: Optional[str]
    stage: str = "Applied"
    resume_url: Optional[str]
    notes: Optional[str]
    recruiter_comments: Optional[str]
    source: Optional[str] = Field(default="Unknown")  # LinkedIn | Referral | Naukri | Career Page | Unknown — how this candidate entered the pipeline
    applications: List["Application"] = Relationship(back_populates="candidate")

class Stage(SQLModel, table=True):
        id: Optional[int] = Field(default=None, primary_key=True)
        name: str
        order: int
        stage_type: Optional[str] = Field(default="Screening")  # Screening | Interview | Decision | Final

class Application(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id")
    candidate_id: int = Field(foreign_key="candidate.id")
    candidate_name: str
    candidate_email: str
    stage: str = "Applied"  
    source: Optional[str] = Field(default=None)  # LinkedIn | Referral | Naukri | Career Page | ... — set by whatever creates the application; NULL for existing/legacy rows
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    applied_at: datetime = Field(default_factory=datetime.utcnow)
    hired_at: Optional[datetime] = None
    job: Job = Relationship(back_populates="applications")
    candidate: Candidate = Relationship(back_populates="applications")

class IntegrationConnection(SQLModel, table=True):
    # Records which third-party integrations an admin has toggled on —
    # deliberately NOT a real OAuth connection. There is no Slack/Gmail/
    # Google Calendar app registration (client_id/secret/redirect URI)
    # anywhere in this backend, so "Connect" here does not actually talk to
    # those services. This just persists the on/off state honestly instead
    # of faking it as purely client-side (which reset on every reload).
    id: Optional[int] = Field(default=None, primary_key=True)
    integration_id: str = Field(unique=True)  # 'slack' | 'gmail' | 'google-calendar'
    status: str = Field(default="disconnected")  # 'connected' | 'disconnected'
    connected_at: Optional[datetime] = None


class CandidateComment(SQLModel, table=True):
    # Real threaded discussion for the Pipeline Collaboration board — separate
    # from Candidate.recruiter_comments (a single free-text field) since the
    # UI needs multiple, attributed, timestamped entries per candidate.
    id: Optional[int] = Field(default=None, primary_key=True)
    candidate_id: int = Field(foreign_key="candidate.id")
    author: str
    text: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AIInterviewTemplate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    interview_type: str
    questions: List[dict] = Field(default_factory=list, sa_column=Column(SA_JSON))
    time_limit: Optional[int] = None
    difficulty: Optional[str] = None
    created_by: Optional[int] = Field(foreign_key="user.id")

class Assessment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    type: str
    skill: Optional[str] = None
    difficulty: Optional[str] = None
    role: Optional[str] = None
    question_count: int = 0
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[int] = Field(default=None, foreign_key="user.id")

class Assignment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    candidate_id: Optional[int] = None  
    assessment_id: int = Field(foreign_key="assessment.id")
    due_date: Optional[date] = None
    status: str = "Assigned"

class AssessmentCandidatePreselection(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    candidate_ids: List[int] = Field(default_factory=list, sa_column=Column(SA_JSON))
    candidate_emails: List[str] = Field(default_factory=list, sa_column=Column(SA_JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)



class OfferStatus(str, enum.Enum):
    draft = "Draft"
    sent = "Sent"
    accepted = "Accepted"
    rejected = "Rejected"
    expired = "Expired"

class OfferTemplate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    position: Optional[str] = None
    department: Optional[str] = None
    template_content: str = Field(sa_column=Column(Text))
    salary_range_min: Optional[float] = None
    salary_range_max: Optional[float] = None
    benefits: List[str] = Field(default_factory=list, sa_column=Column(SA_JSON))
    validity_days: int = 30  
    created_by: Optional[int] = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class OfferTracking(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    candidate_id: Optional[int] = Field(default=None, foreign_key="candidate.id")
    job_id: Optional[int] = Field(default=None, foreign_key="job.id")
    template_id: Optional[int] = Field(default=None, foreign_key="offertemplate.id")
    candidate_name: str
    candidate_email: str
    position: str
    department: Optional[str] = None
    salary_offered: Optional[float] = None
    benefits: List[str] = Field(default_factory=list, sa_column=Column(SA_JSON))
    offer_content: str = Field(sa_column=Column(Text))
    status: OfferStatus = OfferStatus.draft
    sent_date: Optional[datetime] = None
    response_date: Optional[datetime] = None
    expiry_date: Optional[date] = None
    notes: Optional[str] = Field(sa_column=Column(Text))
    created_by: Optional[int] = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class LegacyQuestion(Base):
    __tablename__ = "aptitude_questions"
    id = Column(Integer, primary_key=True, index=True)
    set_no = Column(Integer, nullable=True)
    question = Column(String, nullable=False)
    options = Column(SA_JSON, nullable=False)
    answer = Column(String, nullable=False)

class LegacyCandidate(Base):
    __tablename__ = "aptitude_assessment_results"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    verified = Column(Integer, default=0)
    score = Column(Integer, nullable=True)
    status = Column(String, nullable=True)
    answers = Column(SA_JSON, nullable=True)


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    date = Column(Date, nullable=False)
    status = Column(String, default="Present")  # Present / Absent / Late / Half Day
    check_in = Column(String, nullable=True)
    check_out = Column(String, nullable=True)
    remarks = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class LeaveRequest(Base):
    __tablename__ = "leave_requests"
    id = Column(Integer, primary_key=True, index=True)
    # Nullable so rows created before this column existed stay valid.
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    leave_type = Column(String, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    is_half_day = Column(Boolean, default=False, nullable=False, server_default="false")
    reason = Column(String)
    status = Column(SAEnum(LeaveStatus), default=LeaveStatus.pending)
    approved_by = Column(Integer, nullable=True)
    rejection_reason = Column(String, nullable=True)
    applied_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)



UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

class OnboardingCandidate(Base):
    __tablename__ = "candidates_onboarding"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    documents = relationship("OnboardingDocument", back_populates="candidate", cascade="all, delete-orphan")

class OnboardingDocument(Base):
    __tablename__ = "documents_onboarding"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    filename = Column(String, nullable=True)
    status = Column(SAEnum(DocStatus, name="docstatus_enum"), default=DocStatus.pending)
    candidate_id = Column(Integer, ForeignKey("candidates_onboarding.id"))
    candidate = relationship("OnboardingCandidate", back_populates="documents")

class Signature(Base):
    __tablename__ = "signatures"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)

class CandidateRecord(Base):
    __tablename__ = "candidate_records"
    id = Column(Integer, primary_key=True, index=True)
    role = Column(String(120), index=True)
    experience_level = Column(String(50), index=True)

    candidate_name = Column(String(200))
    candidate_email = Column(String(200), index=True)
    candidate_skills = Column(Text)
    candidate_experience_text = Column(Text)

    resume_text = Column(Text)
    jd_text = Column(Text)
    score = Column(Float)

    resume_filename = Column(String(300))
    email_sent = Column(String(20), default="no")
    resume_screened = Column(String(20), default="no")  
    stage = Column(String(50), default="Applied", index=True)  
    created_at = Column(DateTime, default=datetime.utcnow)

def init_db():
    Base.metadata.create_all(bind=engine, checkfirst=True)

class InterviewCandidate(Base):
    __tablename__ = "candidates"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    otp = Column(String, nullable=True)
    otp_created_at = Column(DateTime, nullable=True)

class Question(Base):
    __tablename__ = "questions"
    id = Column(Integer, primary_key=True, index=True)
    question_text = Column(Text, nullable=False)
    question_type = Column(String, default="text")  

class Answer(Base):
    __tablename__ = "answers"
    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"))  
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=True)  
    question_text = Column(Text, nullable=True)  
    template_question_index = Column(Integer, nullable=True)  
    answer_text = Column(Text, nullable=True)
    audio_path = Column(String, nullable=True)  
    video_path = Column(String, nullable=True) 
    score = Column(Integer, nullable=True)

    candidate = relationship("InterviewCandidate", foreign_keys=[candidate_id])
    question = relationship("Question", foreign_keys=[question_id])



# def init_db():
#     """
#     Initialize all tables
#     """
#     SQLModel.metadata.create_all(bind=engine)
#     Base.metadata.create_all(bind=engine)
#     print("Tables initialized.")

class SavedJob(SQLModel, table=True):
    __tablename__ = "saved_jobs"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    job_id: int = Field(foreign_key="job.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    user: Optional["User"] = Relationship()
    job: Optional["Job"] = Relationship()


class Notifications(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    message = Column(String, nullable=False)
    is_read = Column(Boolean, default=False)