# main.py
import os
import base64
from fastapi import FastAPI, Request, Depends
from core.dependencies import get_current_user, require_roles, verify_self_or_hr
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel, Session, select
from core.database import engine, Base
from model.models import User
import model.Productivity
import model.onboarding.buddy_mentor
import model.onboarding.employee
import model.Employee_Management.org_hierarchy
import model.Employee_Management.employee_lifecycle
import model.Employee_Management.employee_master
import model.Employee_Management.employee_document
import model.Payroll.Payroll_Processing
from sqladmin import Admin, ModelView


# CREATE FASTAPI APP  (THIS MUST COME FIRST)

app = FastAPI(title="AI Recruitment HR Platform")


@app.get("/")
def root():
    return {"status": "ok", "service": "AI Recruitment HR Platform"}


# ADMIN BASIC AUTH MIDDLEWARE

# @app.middleware("http")
# async def admin_protect(request: Request, call_next):
 
#     if request.url.path.startswith("/admin"):
#         auth = request.headers.get("Authorization")
 
#         if not auth or not auth.startswith("Basic "):
#             return Response(
#                 status_code=401,
#                 headers={
#                     "WWW-Authenticate": 'Basic realm="AdminPanel"',
#                     "Cache-Control": "no-store"
#                 },
#                 content="Authentication required"
#             )
 
#         try:
#             encoded = auth.split(" ")[1]
#             decoded = base64.b64decode(encoded).decode()
#             username, password = decoded.split(":", 1)
 
#             ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
#             ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
 
#             if username != ADMIN_USERNAME or password != ADMIN_PASSWORD:
#                 return Response(
#                     status_code=401,
#                     headers={
#                         "WWW-Authenticate": 'Basic realm="AdminPanel"',
#                         "Cache-Control": "no-store"
#                     },
#                     content="Invalid username or password"
#                 )
 
#         except Exception:
#             return Response(
#                 status_code=401,
#                 headers={
#                     "WWW-Authenticate": 'Basic realm="AdminPanel"',
#                     "Cache-Control": "no-store"
#                 },
#                 content="Invalid authentication format"
#             )
 
#     return await call_next(request)
 
 

# IMPORT ROUTERS

from routers.admin_users.auth import router as auth_router
from routers.jobs import router as jobs_router
from routers.admin_users.admin import router as admin_router, compat_router as admin_compat_router
from routers.candidates import router as candidates_router
from routers.admin_users.recruiter_dashboard import router as recruiter_dashboard_router
from routers.admin_users.Dashboard import router as admin_dashboard_router
from routers.pipeline import router as pipeline_router
from routers.Analytics_Dashboard.analytics import router as analytics_router
from routers.HR_Automation.digital_signature.routers.documents import router as documents_router
from routers.HR_Automation.digital_signature.routers.signatures import router as signatures_router
from routers.Candidate_assessments.Assessment.Assessments.assessments_router import router as assessments_router
from routers.Candidate_assessments.Assessment.Assessments.assignments_router import router as assignments_router
from routers.Candidate_assessments.Assessment.Assessments.ai_interview_router import router as ai_interview_router
from routers.Candidate_assessments.Assessment.communication.comm_routes import router as comm_router
from routers.Candidate_assessments.Assessment.coding.coding import router as coding_router
from routers.Candidate_assessments.Assessment.Assessments.Assessment_Result.candidates import router as candidates_result_router
from routers.Candidate_assessments.Assessment.aptitude.routers import exam, results as aptitude_results
from routers.Basic_analytics.hiring_funnel.routers.hiring_funnel import router as hiring_funnel_router
from routers.Basic_analytics.Time_to_hire.time_hire import router as time_hire_router
from routers.HR_Automation.Task_Management.router.tasks_router import router as tasks_router
from routers.Resume_parsing.routers.resume_router import router as resume_router
from routers.admin_users.send_assessment_email import router as email_router
from routers.offers.offer_template_router import router as offer_template_router
from routers.offers.offer_tracking_router import router as offer_tracking_router
from routers.HR_Automation.Onboarding.routers import candidates as onboard_candidates, uploads
from routers.AI_Interview_Bot.routes import interviews
from routers.CRM import contacts, company, deals, leads, pipelines, activities, analytics,projects, clients, tasks
from routers.onboarding.admin_candidates import router as admin_candidates_router
from routers.onboarding.convert_to_employee import router as convert_to_employee_router
from routers.onboarding import bank_details, present_address, statutory, onboarding, approval, employee, family_details, documents, personal_info, address, background_verification, probation_management, induction, buddy_mentor, offer_letter, basic_details, contact_details
from routers.billing import subscription as billing_subscription
from routers.integrations import connections as integrations_connections
from routers.HR_Operations.Asset_Management import assets, asset_allocation, asset_return, asset_maintenance,asset_insurance
from routers.Company_Settings import currency, financial_year, localization, policy,company_profile,notification_preference,location,data_privacy,announcements
from routers.Payroll import Payroll_Processing
from routers.Payroll import salary_structure, payroll_run, salary_slip, reimbursements, loans_advances, statutory_compliance, bank_transfer, final_settlement, payroll_reports as payroll_rpt, payroll_integration
from routers.Employee_Management import employee_master, all_employees, document_vault, org_hierarchy, employee_lifecycle, employee_self_service
from routers.HR_Operations import exit_management, letter_generation, notice_period, hr_helpdesk, employee_confirmation, transfers, promotions
from routers.HR_Automation.attendance.routers import (
    shift_management, holiday_calendar, work_hour_rules,
    attendance_reports, monthly_attendance, leave,
    attendance_capture, daily_punches, daily_attendance,
    manual_attendance, leave_correction, regularization
)
from routers.HR_Automation.attendance.routers import attendance as basic_attendance
from routers.Reports import employee_reports, attendance_reports as rep_att, leave_reports, payroll_reports as rep_pay, compliance_reports, custom_report_builder, executive_dashboard, ai_insights
from routers.Forms_Workflows import custom_form_builder, workflow_engine, request_management, surveys, approvals



from routers.Productivity.productivity_router import router as productivity_router
from routers.Productivity.activity_router import router as activity_router
from routers.Productivity.projects_router import router as projects_router
from routers.Productivity.tasks_router import router as prod_tasks_router
from routers.Productivity.screenshot_router import router as screenshot_router
from routers.Productivity.analytics_router import router as prod_analytics_router
from routers.Productivity.insights_router import router as insights_router
from routers.Productivity.alerts_router import router as alerts_router
from routers.Productivity.admin_productivity_router import router as admin_productivity_router
from routers.Productivity.admin_reports_router import router as admin_reports_router
from routers.Productivity.admin_config_router import router as admin_config_router
from routers.Productivity.dashboard_router import router as prod_dashboard_router
from routers.Productivity.realtime_router import router as realtime_router
from routers.Productivity.time_tracking_router import router as time_tracking_router
from routers.Productivity.download_router import router as download_router
from routers.Productivity.settings_router import router as prod_settings_router
from routers.Productivity.notifications_router import router as prod_notifications_router
from routers.candidates.auth import router as candidate_auth_router
from super_admin import roles_permissions, multi_tenant, company_settings_admin, role_assignments
...


# CORS

app.add_middleware(
    CORSMiddleware,
    allow_origins=[     "http://localhost:3000",     "http://127.0.0.1:3000",     "https://hr-ai-levitica.vercel.app",  "http://localhost:5173", "http://127.0.0.1:5173",],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
 
 

# STARTUP — CREATE TABLES & DEFAULT SUPERADMIN

@app.on_event("startup")
def on_startup():
    try:
        # Try to create tables
        SQLModel.metadata.create_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        print(" Database tables initialized successfully")
    except Exception as e:
        print(f" Warning: Could not create database tables: {e}")
        print("  The application will continue, but database operations may fail.")
        print("  Please ensure PostgreSQL is running and DATABASE_URL is correct.")
        return  # Exit early if database connection fails
 
    try:
        # Try to create default superadmin
        with Session(engine) as session:
            existing = session.exec(
                select(User).where(User.email == "superadmin@example.com")
            ).first()

            if not existing:
                from passlib.context import CryptContext
                pwd = CryptContext(schemes=["bcrypt"])

                admin = User(
                    name="Super Admin",
                    username="superadmin",
                    email="superadmin@example.com",
                    hashed_password=pwd.hash("admin123"),
                    role="superadmin",
                    is_active=True
                )

                session.add(admin)
                session.commit()

                print("SUPERADMIN CREATED")
            else:
                print("SUPERADMIN EXISTS")
    except Exception as e:
        print(f" Warning: Could not create default superadmin: {e}")
        print("  You may need to create it manually once the database is available.")
 
 

# SQLADMIN PANEL 
class UserAdmin(ModelView, model=User):
    column_list = [User.id, User.username, User.email, User.role, User.is_active, User.created_at]
    form_columns = [User.username, User.email, User.role, User.is_active]
    name = "User"
    name_plural = "Users"
    icon = "fa-solid fa-user"
 
admin = Admin(app=app, engine=engine, title="Super Admin Dashboard")
admin.add_view(UserAdmin)

# ROUTE REGISTRATION
app.include_router(auth_router)
app.include_router(jobs_router,               prefix="/api/jobs")
app.include_router(admin_router,              prefix="/api/admin")
app.include_router(admin_compat_router)
app.include_router(candidates_router)
app.include_router(pipeline_router,            prefix="/api/pipeline")
app.include_router(recruiter_dashboard_router, prefix="/api/recruiter_dashboard")
app.include_router(admin_dashboard_router,     prefix="/api/dashboard")
app.include_router(analytics_router)
app.include_router(assessments_router)
app.include_router(assignments_router)
app.include_router(candidates_result_router,   prefix="/api/assessment_results")
app.include_router(ai_interview_router)
app.include_router(comm_router,                prefix="/comm")
app.include_router(coding_router,              prefix="/coding")
app.include_router(exam.router,                prefix="/api/assessment/aptitude")
app.include_router(aptitude_results.router,    prefix="/api/assessment/aptitude")
app.include_router(hiring_funnel_router,       prefix="/api/hiring_funnel")
app.include_router(time_hire_router,           prefix="/api/time_to_hire")
_hr_auth = [Depends(require_roles(["superadmin", "admin", "company", "hr_admin"]))]
app.include_router(basic_attendance.router,      prefix="/api/attendance", tags=["Attendance"], dependencies=_hr_auth)
# leave.router already carries prefix="/leave"; mounting it at "/api/leave" produced /api/leave/leave/*.
app.include_router(leave.router,               prefix="/api", dependencies=_hr_auth)
app.include_router(documents_router,           prefix="/api/documents", dependencies=_hr_auth)
app.include_router(signatures_router,          prefix="/api/signatures", dependencies=_hr_auth)
# onboard_candidates.router is mounted at prefix="/api" with an internal
# "/candidates" prefix, landing on /api/candidates/*, /api/candidates/list —
# the SAME path prefix the real candidate-portal router (routers/candidates,
# `candidates_router` above) uses. Checked both routers' exact routes: no
# actual overlap (portal router only defines /applications, /profile,
# /jobsearch, /savedjobs, /recentapplications, /recommendedjobs,
# /notifications — never a bare "/" or "/list"), so this is safe to secure.
# This one manages Candidate records for the internal ATS/onboarding flow
# (HR staff pre-creating a candidate record when onboarding a new hire),
# not the job-seeker-facing side, hence HR-tier auth rather than open to
# recruiters.
app.include_router(onboard_candidates.router,  prefix="/api", dependencies=_hr_auth)  # router self-prefix="/candidates" -> /api/candidates/*
app.include_router(uploads.router,             prefix="/api/uploads", dependencies=_hr_auth)
app.include_router(tasks_router,               prefix="/api/tasks", dependencies=_hr_auth)
app.include_router(resume_router,              prefix="/api/resume")
app.include_router(interviews.router,          prefix="/api/interviews")
app.include_router(email_router)
app.include_router(offer_template_router,      prefix="/api/offers")
app.include_router(offer_tracking_router,      prefix="/api/offers")

# Additional CRM Modules
# SECURITY FIX: these previously had no auth check at all (only Depends(get_db)
# inside each route) — anyone, logged in or not, could read/write CRM data.
# Enforcing login here at the router-mount level closes that without having
# to edit every individual route function in routers/CRM/*.
_crm_auth = [Depends(require_roles(["superadmin", "admin", "company"]))]
app.include_router(contacts.router,    prefix="/contacts",tags=["contacts"], dependencies=_crm_auth)
app.include_router(company.router,     prefix="/companies",tags=["companies"], dependencies=_crm_auth)
app.include_router(deals.router,       prefix="/deals",tags=["deals"], dependencies=_crm_auth)
app.include_router(leads.router,       prefix="/api/leads", tags=["leads"], dependencies=_crm_auth)
# Legacy compatibility for existing frontend calls.
app.include_router(leads.router,       prefix="/leads", tags=["leads-legacy"], include_in_schema=False, dependencies=_crm_auth)
app.include_router(pipelines.router,   prefix="/pipelines",tags=["pipelines"], dependencies=_crm_auth)
app.include_router(activities.router,  prefix="/activities",tags=["activities"], dependencies=_crm_auth)
app.include_router(analytics.router,   prefix="/analytics",tags=["analytics"], dependencies=_crm_auth)
app.include_router(clients.router, dependencies=_crm_auth)
app.include_router(projects.router, dependencies=_crm_auth)
app.include_router(tasks.router, dependencies=_crm_auth)

# Onboarding Routes
    
app.include_router(admin_candidates_router)
app.include_router(convert_to_employee_router)
app.include_router(bank_details.router)
app.include_router(present_address.router)
app.include_router(statutory.router)
app.include_router(onboarding.router)
app.include_router(approval.router)
app.include_router(employee.router)
app.include_router(family_details.router)
app.include_router(documents.router)
app.include_router(personal_info.router)
app.include_router(address.router)
app.include_router(background_verification.router)
app.include_router(probation_management.router) 
app.include_router(induction.router)
app.include_router(buddy_mentor.router)
app.include_router(offer_letter.router)
app.include_router(basic_details.router)
app.include_router(contact_details.router)
app.include_router(billing_subscription.router)
app.include_router(integrations_connections.router)

# Company Settings - Currency Management
app.include_router(currency.router) 
app.include_router(financial_year.router)
app.include_router(localization.router)
app.include_router(policy.router)
app.include_router(company_profile.router)
app.include_router(notification_preference.router)
app.include_router(location.router)
app.include_router(data_privacy.router)
app.include_router(announcements.router)

#HR Operations - Assets Management
# SECURITY FIX: Asset_Management routers previously had NO auth at all.
_asset_mgmt_auth = [Depends(require_roles(["superadmin", "admin", "company", "hr_admin"]))]
app.include_router(assets.router, dependencies=_asset_mgmt_auth)
app.include_router(asset_allocation.router, dependencies=_asset_mgmt_auth)
app.include_router(asset_return.router, dependencies=_asset_mgmt_auth)
app.include_router(asset_maintenance.router, dependencies=_asset_mgmt_auth)
app.include_router(asset_insurance.router, dependencies=_asset_mgmt_auth)


# Payroll
# SECURITY FIX: every Payroll router previously had NO auth check at all —
# anyone, logged in or not, could generate payroll, view salary slips, run
# bank transfers, and see loan/reimbursement data. This is the most
# sensitive data in the whole app, so it's locked to the same HR-tier roles
# as Company Settings/Employee Management. Employees still see their OWN
# payslip separately via the properly-scoped employee_self_service.py.
_payroll_auth = [Depends(require_roles(["superadmin", "admin", "company", "hr_admin"]))]
app.include_router(salary_structure.router,     prefix="/api/payroll", tags=["Payroll"], dependencies=_payroll_auth)
app.include_router(payroll_run.router,          prefix="/api/payroll", tags=["Payroll"], dependencies=_payroll_auth)
app.include_router(salary_slip.router,          prefix="/api/payroll", tags=["Payroll"], dependencies=_payroll_auth)
app.include_router(reimbursements.router,       prefix="/api/payroll", tags=["Payroll"], dependencies=_payroll_auth)
app.include_router(loans_advances.router,       prefix="/api/payroll", tags=["Payroll"], dependencies=_payroll_auth)
app.include_router(statutory_compliance.router, prefix="/api/payroll", tags=["Payroll"], dependencies=_payroll_auth)
app.include_router(bank_transfer.router,        prefix="/api/payroll", tags=["Payroll"], dependencies=_payroll_auth)
app.include_router(final_settlement.router,     prefix="/api/payroll", tags=["Payroll"], dependencies=_payroll_auth)
app.include_router(payroll_rpt.router,          prefix="/api/payroll", tags=["Payroll"], dependencies=_payroll_auth)
app.include_router(Payroll_Processing.router,   prefix="/api/payroll", tags=["Payroll"], dependencies=_payroll_auth)
app.include_router(payroll_integration.router,  prefix="/api/payroll", tags=["Payroll"], dependencies=_payroll_auth)
# Employee Management
# SECURITY FIX: employee_master, document_vault, employee_lifecycle, and
# employee_self_service had NO auth check whatsoever — not even a login
# requirement (unlike all_employees.router and org_hierarchy.router, which
# already enforce their own role checks internally, so they're left as-is
# here to avoid a redundant duplicate check).
_emp_mgmt_auth = [Depends(require_roles(["superadmin", "admin", "company", "hr_admin"]))]
# employee_self_service is the one router in this group that the 'employee'
# role is actually supposed to reach — every other router here
# (employee_master, document_vault, employee_lifecycle) is an HR-only tool
# and stays locked to _emp_mgmt_auth above. verify_self_or_hr additionally
# stops an 'employee' from reading/acting on a DIFFERENT employee_id than
# their own, while leaving HR roles able to access any employee_id as before.
_self_service_auth = [
    Depends(require_roles(["superadmin", "admin", "company", "hr_admin", "employee"])),
    Depends(verify_self_or_hr),
]
app.include_router(employee_master.router,       prefix="/api/employees", tags=["Employee Management"], dependencies=_emp_mgmt_auth)
app.include_router(all_employees.router,         prefix="/api/employees", tags=["Employee Management"])
app.include_router(document_vault.router,        prefix="/api/employees", tags=["Employee Management"], dependencies=_emp_mgmt_auth)
app.include_router(org_hierarchy.router,         prefix="/api/employees", tags=["Employee Management"])
app.include_router(employee_lifecycle.router,    prefix="/api/employees", tags=["Employee Management"], dependencies=_emp_mgmt_auth)
app.include_router(employee_self_service.router, prefix="/api/employees", tags=["Employee Management"], dependencies=_self_service_auth)

# HR Operations
# SECURITY FIX: all 7 HR_Operations routers previously had NO auth at all —
# exit management, employee confirmations, transfers, promotions, and HR
# helpdesk admin stats/reports were all reachable without logging in.
_hr_ops_auth = [Depends(require_roles(["superadmin", "admin", "company", "hr_admin"]))]
app.include_router(exit_management.router,       prefix="/api/hr-ops", tags=["HR Operations"], dependencies=_hr_ops_auth)
app.include_router(letter_generation.router,     prefix="/api/hr-ops", tags=["HR Operations"], dependencies=_hr_ops_auth)
app.include_router(notice_period.router,         prefix="/api/hr-ops", tags=["HR Operations"], dependencies=_hr_ops_auth)
app.include_router(hr_helpdesk.router,           prefix="/api/hr-ops", tags=["HR Operations"], dependencies=_hr_ops_auth)
app.include_router(employee_confirmation.router, prefix="/api/hr-ops", tags=["HR Operations"], dependencies=_hr_ops_auth)
app.include_router(transfers.router,             prefix="/api/hr-ops", tags=["HR Operations"], dependencies=_hr_ops_auth)
app.include_router(promotions.router,            prefix="/api/hr-ops", tags=["HR Operations"], dependencies=_hr_ops_auth)

# Attendance extensions
app.include_router(shift_management.router,       prefix="/api/attendance", tags=["Attendance"], dependencies=_hr_auth)
app.include_router(holiday_calendar.router,       prefix="/api/attendance", tags=["Attendance"], dependencies=_hr_auth)
app.include_router(work_hour_rules.router,        prefix="/api/attendance", tags=["Attendance"], dependencies=_hr_auth)
# app.include_router(att_rpt.router,                prefix="/api/attendance", tags=["Attendance"])
app.include_router(attendance_capture.router,     prefix="/api/attendance", tags=["Attendance"], dependencies=_hr_auth)
app.include_router(daily_punches.router,          prefix="/api/attendance", tags=["Attendance"], dependencies=_hr_auth)
app.include_router(daily_attendance.router,       prefix="/api/attendance", tags=["Attendance"], dependencies=_hr_auth)
app.include_router(manual_attendance.router,      prefix="/api/attendance", tags=["Attendance"], dependencies=_hr_auth)
app.include_router(leave_correction.router,       prefix="/api/attendance", tags=["Attendance"], dependencies=_hr_auth)
app.include_router(monthly_attendance.router,     prefix="/api/attendance", tags=["Attendance"], dependencies=_hr_auth)
app.include_router(regularization.router,         prefix="/api/attendance", tags=["Attendance"], dependencies=_hr_auth)
app.include_router(attendance_reports.router,     prefix="/api/attendance", tags=["Attendance"], dependencies=_hr_auth)
# leave.router already mounted at /api/leave (line above attendance block); not duplicated here

# Reports
app.include_router(employee_reports.router,      prefix="/api/reports", tags=["Reports"])
app.include_router(rep_att.router,               prefix="/api/reports", tags=["Reports"])
app.include_router(leave_reports.router,         prefix="/api/reports", tags=["Reports"])
app.include_router(rep_pay.router,               prefix="/api/reports", tags=["Reports"])
app.include_router(compliance_reports.router,    prefix="/api/reports", tags=["Reports"])
app.include_router(custom_report_builder.router, prefix="/api/reports", tags=["Reports"])
app.include_router(executive_dashboard.router,   prefix="/api/reports", tags=["Reports"])
app.include_router(ai_insights.router,           prefix="/api/reports", tags=["Reports"])

# Productivity



app.include_router(productivity_router,       prefix="/api/productivity", tags=["Productivity"])
app.include_router(activity_router,           prefix="/api/productivity", tags=["Productivity"])
app.include_router(projects_router,           prefix="/api/productivity", tags=["Productivity"])
app.include_router(prod_tasks_router,         prefix="/api/productivity", tags=["Productivity"])
app.include_router(screenshot_router,         prefix="/api/productivity", tags=["Productivity"])
app.include_router(prod_analytics_router,     prefix="/api/productivity", tags=["Productivity"])
app.include_router(insights_router,           prefix="/api/productivity", tags=["Productivity"])
app.include_router(alerts_router,             prefix="/api/productivity", tags=["Productivity"])
app.include_router(admin_productivity_router, prefix="/api/productivity", tags=["Productivity"])
app.include_router(admin_reports_router,      prefix="/api/productivity", tags=["Productivity"])
app.include_router(admin_config_router,       prefix="/api/productivity", tags=["Productivity"])
app.include_router(prod_dashboard_router,     prefix="/api/productivity", tags=["Productivity"])
app.include_router(realtime_router,           prefix="/api/productivity", tags=["Productivity"])
app.include_router(time_tracking_router,      prefix="/api/productivity", tags=["Productivity"])
app.include_router(download_router,           prefix="/api/productivity", tags=["Productivity"])
app.include_router(prod_settings_router,      prefix="/api/productivity", tags=["Productivity"])
app.include_router(prod_notifications_router, prefix="/api/productivity", tags=["Productivity"])

# Forms & Workflows
app.include_router(custom_form_builder.router, prefix="/api/forms", tags=["Forms & Workflows"])
app.include_router(workflow_engine.router,     prefix="/api/forms", tags=["Forms & Workflows"])
app.include_router(request_management.router,  prefix="/api/forms", tags=["Forms & Workflows"])
app.include_router(surveys.router,             prefix="/api/forms", tags=["Forms & Workflows"])
app.include_router(approvals.router,           prefix="/api/forms", tags=["Forms & Workflows"])

# Candidate Auth
app.include_router(candidate_auth_router, prefix="/api/candidate", tags=["Candidate Auth"])

# Super Admin
app.include_router(roles_permissions.router,      prefix="/api/super-admin", tags=["Super Admin"])
app.include_router(multi_tenant.router,           prefix="/api/super-admin", tags=["Super Admin"])
app.include_router(company_settings_admin.router, prefix="/api/super-admin", tags=["Super Admin"])
app.include_router(roles_permissions.router,      prefix="/api/super-admin", tags=["Super Admin"])
app.include_router(role_assignments.router,       prefix="/api/super-admin", tags=["Super Admin"])
 

# STATIC FILES

if not os.path.exists("uploads"):
    os.makedirs("uploads")
 
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
 
# TEST ENDPOINT
@app.get("/api/test")
def test_api():
    return {"message": "Backend is working correctly!"}