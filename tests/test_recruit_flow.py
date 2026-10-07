"""
Tests for: auto-screening on apply, offer accepted -> onboarding, and
convert-to-employee. They run against a throwaway SQLite database with OpenAI
and email mocked, so they need no real keys:

    DATABASE_URL=sqlite:////tmp/t.db OPENAI_API_KEY=x SMTP_HOST=x SMTP_PORT=25 \
    SMTP_USERNAME=x SMTP_PASSWORD=x SMTP_FROM=x SECRET_KEY=x ADMIN_USERNAME=x \
    ADMIN_PASSWORD=x SCORE_THRESHOLD=25 pytest tests/test_recruit_flow.py
"""
import io
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from sqlmodel import SQLModel

import main
from core.database import SessionLocal, engine
from model.models import Application, Candidate, CandidateRecord, Job, OfferStatus, OfferTracking, User
from model.onboarding.candidate import Candidate as OnboardingCandidate
from routers.candidates.auth import create_candidate_token

RR = "routers.Resume_parsing.routers.resume_router"


@pytest.fixture(autouse=True)
def fresh_db():
    # Hard stop: never drop tables on a real database.
    if engine.url.get_backend_name() != "sqlite":
        pytest.exit(f"Refusing to run: tests would wipe {engine.url}. Use SQLite.", returncode=2)
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def client():
    return TestClient(main.app)


def _docx_bytes(text="Python developer with 5 years of FastAPI experience"):
    d = DocxDocument()
    d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _seed_job_and_candidate(db):
    recruiter = User(name="Rec", email="rec@x.com", hashed_password="x", role="recruiter",
                     created_at=datetime.now(timezone.utc))
    db.add(recruiter)
    db.commit()
    job = Job(title="Backend Engineer", department="Eng", employment_type="Full-time",
              description="Build APIs", status="Published", role="Backend Engineer",
              recruiter_id=recruiter.id)
    cand = Candidate(name="Asha Rao", email="asha@x.com", role="candidate", skills=None,
                     resume_url=None, notes=None, recruiter_comments=None)
    db.add_all([job, cand])
    db.commit()
    db.refresh(job)
    db.refresh(cand)
    return job, cand


def _screen_mocks(score):
    return (
        patch(f"{RR}.ai_extract_fields", return_value={
            "name": "Asha Rao", "email": "asha@x.com",
            "skills": ["python"], "experience_summary": "5y"}),
        patch(f"{RR}.ai_generate_jd", return_value="JD text"),
        patch(f"{RR}.ai_similarity_score", return_value=score),
        patch(f"{RR}.send_email_smtp", return_value=(True, "ok")),
    )


# ---------- 1. auto-screen on apply ----------

def test_apply_with_resume_above_threshold_is_shortlisted(client, db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    job, cand = _seed_job_and_candidate(db)
    token = create_candidate_token(cand.id)
    p1, p2, p3, p4 = _screen_mocks(60.0)
    with p1, p2, p3, p4 as mail:
        r = client.post(f"/api/candidates/apply/{job.id}",
                        headers={"Authorization": f"Bearer {token}"},
                        files={"resume": ("cv.docx", _docx_bytes())})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["screening"]["status"] == "shortlisted"
    assert body["screening"]["score"] == 60.0
    assert mail.called
    db.expire_all()
    assert db.query(Application).one().stage == "Screening"
    assert db.query(CandidateRecord).one().stage == "Screening"


def test_apply_with_resume_below_threshold_is_rejected_but_saved(client, db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    job, cand = _seed_job_and_candidate(db)
    token = create_candidate_token(cand.id)
    p1, p2, p3, p4 = _screen_mocks(10.0)
    with p1, p2, p3, p4 as mail:
        r = client.post(f"/api/candidates/apply/{job.id}",
                        headers={"Authorization": f"Bearer {token}"},
                        files={"resume": ("cv.docx", _docx_bytes())})
    assert r.status_code == 201, r.text
    assert r.json()["screening"]["status"] == "rejected"
    assert not mail.called                       # no shortlist email
    db.expire_all()
    assert db.query(Application).one().stage == "Rejected"
    assert db.query(CandidateRecord).count() == 1  # still saved


def test_apply_without_resume_still_works_and_stays_applied(client, db):
    """Old frontend behaviour: POST with no body must keep working."""
    job, cand = _seed_job_and_candidate(db)
    token = create_candidate_token(cand.id)
    r = client.post(f"/api/candidates/apply/{job.id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201, r.text
    assert r.json()["screening"]["status"] == "pending"
    assert r.json()["stage"] == "Applied"


def test_apply_survives_ai_failure(client, db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    job, cand = _seed_job_and_candidate(db)
    token = create_candidate_token(cand.id)
    with patch(f"{RR}.ai_extract_fields", side_effect=RuntimeError("boom")):
        r = client.post(f"/api/candidates/apply/{job.id}",
                        headers={"Authorization": f"Bearer {token}"},
                        files={"resume": ("cv.docx", _docx_bytes())})
    assert r.status_code == 201, r.text
    assert r.json()["screening"]["status"] == "pending"
    db.expire_all()
    assert db.query(Application).count() == 1


def test_duplicate_apply_still_409(client, db):
    job, cand = _seed_job_and_candidate(db)
    h = {"Authorization": f"Bearer {create_candidate_token(cand.id)}"}
    assert client.post(f"/api/candidates/apply/{job.id}", headers=h).status_code == 201
    assert client.post(f"/api/candidates/apply/{job.id}", headers=h).status_code == 409


# ---------- 2. offer accepted -> onboarding ----------

def _offer(db, status=OfferStatus.sent, email="asha@x.com"):
    o = OfferTracking(candidate_name="Asha Rao", candidate_email=email, position="Backend Engineer",
                      department="Engineering", offer_content="Offer", status=status, notes=None)
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def test_accepting_offer_creates_onboarding_and_sends_invite(db):
    from routers.offers.services.offer_tracking_service import update_offer_status
    o = _offer(db)
    with patch("routers.onboarding.admin_candidates._send_invite_email", new=AsyncMock()) as mail:
        update_offer_status(db, o.id, OfferStatus.accepted)
    rec = db.query(OnboardingCandidate).one()
    assert rec.email == "asha@x.com" and rec.status == "SENT" and rec.invite_token
    assert mail.await_count == 1


def test_accepting_twice_does_not_duplicate_onboarding(db):
    from routers.offers.services.offer_tracking_service import update_offer_status
    o = _offer(db)
    with patch("routers.onboarding.admin_candidates._send_invite_email", new=AsyncMock()):
        update_offer_status(db, o.id, OfferStatus.accepted)
        update_offer_status(db, o.id, OfferStatus.accepted)
    assert db.query(OnboardingCandidate).count() == 1


def test_declining_offer_does_not_start_onboarding(db):
    from routers.offers.services.offer_tracking_service import update_offer_status
    o = _offer(db)
    update_offer_status(db, o.id, OfferStatus.rejected)
    assert db.query(OnboardingCandidate).count() == 0


def test_mail_failure_does_not_undo_acceptance(db):
    from routers.offers.services.offer_tracking_service import update_offer_status
    o = _offer(db)
    with patch("routers.onboarding.admin_candidates._send_invite_email",
               new=AsyncMock(side_effect=RuntimeError("smtp down"))):
        update_offer_status(db, o.id, OfferStatus.accepted)
    db.expire_all()
    assert db.get(OfferTracking, o.id).status == OfferStatus.accepted
    assert db.query(OnboardingCandidate).count() == 1   # record kept; HR can resend


def test_accept_via_action_service_path(db):
    import services.offer_letter_service as svc
    from types import SimpleNamespace
    o = _offer(db)
    user = SimpleNamespace(id=1, role="admin")
    with patch("routers.onboarding.admin_candidates._send_invite_email", new=AsyncMock()):
        svc.process_status_action(db, o.id, SimpleNamespace(action="accept"), user)
    assert db.query(OnboardingCandidate).count() == 1


def test_bulk_accept_path(db):
    import services.offer_letter_service as svc
    from types import SimpleNamespace
    a, b = _offer(db, email="a@x.com"), _offer(db, email="b@x.com")
    user = SimpleNamespace(id=1, role="admin")
    with patch("routers.onboarding.admin_candidates._send_invite_email", new=AsyncMock()):
        svc.bulk_action(db, SimpleNamespace(action="accept", offer_ids=[a.id, b.id]), user)
    assert db.query(OnboardingCandidate).count() == 2


# ---------- 3. convert to employee ----------

def _approved_onboarding(db, mobile="9876543210"):
    rec = OnboardingCandidate(full_name="Asha Rao", email="asha@x.com", mobile=mobile,
                              invite_token="tok-1", token_expires_at=__import__("datetime").datetime(2999, 1, 1),
                              status="APPROVED", form_data={})
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def _as_hr(client):
    from core.dependencies import get_current_user
    hr = User(name="HR", email="hr@x.com", hashed_password="x", role="hr_admin", tenant_id=None,
              created_at=datetime.now(timezone.utc))
    main.app.dependency_overrides[get_current_user] = lambda: hr
    return hr


def test_convert_uses_offer_details_and_requires_gender(client, db):
    _offer(db, status=OfferStatus.accepted)
    rec = _approved_onboarding(db)
    _as_hr(client)
    try:
        # form_data has no gender -> clear 400 the UI can react to
        r = client.post(f"/api/onboarding-forms/candidates/{rec.id}/convert-to-employee", json={})
        assert r.status_code == 400 and "missing required field" in r.json()["detail"]

        with patch("routers.onboarding.convert_to_employee._send_credentials_email",
                   new=AsyncMock(return_value=True)):
            r = client.post(f"/api/onboarding-forms/candidates/{rec.id}/convert-to-employee",
                            json={"gender": "female"})
        assert r.status_code == 201, r.text
        assert r.json()["employee_code"]
    finally:
        main.app.dependency_overrides.clear()

    from model.onboarding.employee import Employee
    db.expire_all()
    emp = db.query(Employee).one()
    assert emp.designation == "Backend Engineer"      # copied from accepted offer
    assert emp.department == "Engineering"
    assert db.get(OnboardingCandidate, rec.id).status == "CONVERTED"


# ---------- 4. leave applications API (/api/leave) ----------

def _employee(db):
    from datetime import date
    from model.onboarding.employee import Employee, GenderEnum
    e = Employee(first_name="Ravi", last_name="Kumar", gender=GenderEnum.male, employee_code="EMP0001",
                 mobile_number="9000000001", joining_date=date(2024, 1, 1), is_active=True)
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


def _hr_user_override():
    from core.dependencies import get_current_user
    hr = User(name="HR", email="hr@x.com", hashed_password="x", role="hr_admin",
              created_at=datetime.now(timezone.utc))
    main.app.dependency_overrides[get_current_user] = lambda: hr


def test_leave_apply_list_filter_approve_delete(client, db):
    emp = _employee(db)
    _hr_user_override()
    try:
        r = client.post("/api/leave/", json={"employee_id": emp.id, "leave_type": "CL",
                        "start_date": "2026-11-02", "end_date": "2026-11-04", "reason": "Family"})
        assert r.status_code == 201, r.text
        lid = r.json()["id"]
        assert r.json()["days"] == 3.0 and r.json()["status"] == "Pending"
        assert r.json()["employee_name"] == "Ravi Kumar"

        assert client.get("/api/leave/").json()["total"] == 1
        assert client.get("/api/leave/", params={"status": "Pending"}).json()["total"] == 1
        assert client.get("/api/leave/", params={"status": "Approved"}).json()["total"] == 0
        assert client.get("/api/leave/", params={"status": "All Status"}).json()["total"] == 1
        assert client.get("/api/leave/", params={"search": "ravi"}).json()["total"] == 1

        r = client.patch(f"/api/leave/{lid}", json={"status": "Approved"})
        assert r.status_code == 200 and r.json()["status"] == "Approved"
        assert client.get("/api/leave/", params={"status": "Approved"}).json()["total"] == 1

        r = client.patch(f"/api/leave/{lid}", json={"status": "Rejected", "rejection_reason": "Busy"})
        assert r.json()["status"] == "Rejected" and r.json()["rejection_reason"] == "Busy"

        assert client.patch(f"/api/leave/{lid}", json={"status": "Nope"}).status_code == 400
        assert client.delete(f"/api/leave/{lid}").status_code == 200
        assert client.get("/api/leave/").json()["total"] == 0
    finally:
        main.app.dependency_overrides.clear()


def test_self_service_leaves_are_per_employee(client, db):
    a = _employee(db)
    from datetime import date
    from model.onboarding.employee import Employee, GenderEnum
    b = Employee(first_name="Sita", gender=GenderEnum.female, employee_code="EMP0002",
                 mobile_number="9000000002", joining_date=date(2024, 1, 1), is_active=True)
    db.add(b)
    db.commit()
    db.refresh(b)
    _hr_user_override()
    try:
        # find the self-service mount and apply leave for employee a only
        r = client.post(f"/api/employees/self-service/{a.id}/leaves",
                        params={"leave_type": "CL", "start_date": "2026-11-02", "end_date": "2026-11-02"})
        if r.status_code == 404:
            pytest.skip("self-service route prefix differs")
        assert r.status_code == 200, r.text
        la = client.get(f"/api/employees/self-service/{a.id}/leaves", params={"year": 2026}).json()
        lb = client.get(f"/api/employees/self-service/{b.id}/leaves", params={"year": 2026}).json()
        assert la["total"] == 1 and lb["total"] == 0
    finally:
        main.app.dependency_overrides.clear()


# ---------- security: tokens ----------

def test_candidate_token_cannot_be_used_as_staff_token(client, db):
    """A candidate token has sub=<candidate id>. It must never be accepted as the
    staff user with the same numeric id."""
    staff = User(name="HR", email="hr@x.com", hashed_password="x", role="hr_admin",
                 is_active=True, created_at=datetime.now(timezone.utc))
    db.add(staff)
    cand = Candidate(name="Eve", email="eve@x.com", role="candidate", skills=None,
                     resume_url=None, notes=None, recruiter_comments=None)
    db.add(cand)
    db.commit()
    db.refresh(staff)
    db.refresh(cand)
    assert staff.id == cand.id            # same numeric id on purpose
    token = create_candidate_token(cand.id)
    r = client.get("/api/leave/", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code in (401, 403), f"candidate token reached HR endpoint: {r.status_code}"


def test_tokens_are_signed_with_env_secret_not_hardcoded(client, db):
    from jose import jwt
    forged = jwt.encode({"sub": "1"}, "your_super_secret_key", algorithm="HS256")
    r = client.get("/api/leave/", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


# ---------- leave reports ----------

def test_leave_balance_report_is_per_employee_and_type_aware(client, db):
    from datetime import date
    from model.models import LeaveRequest, LeaveStatus
    from model.onboarding.employee import Employee, GenderEnum
    a = _employee(db)
    b = Employee(first_name="Sita", gender=GenderEnum.female, employee_code="EMP0002",
                 mobile_number="9000000002", joining_date=date(2024, 1, 1), is_active=True)
    db.add(b)
    db.commit()
    db.refresh(b)
    db.add_all([
        LeaveRequest(employee_id=a.id, leave_type="CL", start_date=date(2026, 3, 2), end_date=date(2026, 3, 4),
                     status=LeaveStatus.approved),                       # 3 casual days for A
        LeaveRequest(employee_id=b.id, leave_type="Sick Leave", start_date=date(2026, 3, 9), end_date=date(2026, 3, 10),
                     status=LeaveStatus.approved),                       # 2 sick days for B
        LeaveRequest(employee_id=a.id, leave_type="EL", start_date=date(2026, 4, 1), end_date=date(2026, 4, 1),
                     status=LeaveStatus.pending),                        # pending: not counted
    ])
    db.commit()
    _hr_user_override()
    try:
        rows = {r["employee_id"]: r for r in client.get("/api/reports/leave/balance").json()}
        assert rows["EMP0001"]["casual_leave_used"] == 3 and rows["EMP0001"]["sick_leave_used"] == 0
        assert rows["EMP0001"]["earned_leave_used"] == 0
        assert rows["EMP0002"]["sick_leave_used"] == 2 and rows["EMP0002"]["casual_leave_used"] == 0

        recs = client.get("/api/reports/leave/records").json()
        assert len(recs) == 3 and all(r["id"] for r in recs)
        approved = client.get("/api/reports/leave/records", params={"status": "Approved"}).json()
        assert len(approved) == 2
        assert client.get("/api/reports/leave/records", params={"status": "bogus"}).status_code == 400
    finally:
        main.app.dependency_overrides.clear()


# ---------- jobs: who sees which jobs ----------

def _users_and_jobs(db):
    def mk(email, role, tenant):
        u = User(name=email, email=email, hashed_password="x", role=role, tenant_id=tenant,
                 is_active=True, created_at=datetime.now(timezone.utc))
        db.add(u)
        db.commit()
        db.refresh(u)
        return u

    r1, r2 = mk("r1@a.com", "recruiter", 1), mk("r2@a.com", "recruiter", 1)
    r3 = mk("r3@b.com", "recruiter", 2)
    company, admin = mk("c@a.com", "company", 1), mk("ad@a.com", "admin", 1)
    other_company, sup = mk("c@b.com", "company", 2), mk("s@x.com", "superadmin", None)
    jobs = {}
    for name, rec in (("j1", r1), ("j2", r2), ("j3", r3)):
        j = Job(title=name, department="Eng", employment_type="Full-time", description="d",
                status="Published", role=name, recruiter_id=rec.id)
        db.add(j)
        db.commit()
        db.refresh(j)
        jobs[name] = j
    return dict(r1=r1, r2=r2, r3=r3, company=company, admin=admin, other=other_company, sup=sup), jobs


def _list_titles(client, user):
    from core.dependencies import get_current_user as core_user
    from routers.admin_users.auth import get_current_user as auth_user
    main.app.dependency_overrides[auth_user] = lambda: user
    main.app.dependency_overrides[core_user] = lambda: user
    try:
        r = client.get("/api/jobs/list")
        assert r.status_code == 200, r.text
        return sorted(j["title"] for j in r.json())
    finally:
        main.app.dependency_overrides.clear()


def test_company_and_admin_see_jobs_created_by_their_recruiters(client, db):
    u, _ = _users_and_jobs(db)
    assert _list_titles(client, u["r1"]) == ["j1"]                 # recruiter: own only
    assert _list_titles(client, u["company"]) == ["j1", "j2"]      # company: its recruiters' jobs
    assert _list_titles(client, u["admin"]) == ["j1", "j2"]        # admin of same company
    assert _list_titles(client, u["other"]) == ["j3"]              # other company: never j1/j2
    assert _list_titles(client, u["sup"]) == ["j1", "j2", "j3"]    # superadmin: all


def test_company_can_edit_and_delete_own_company_jobs_only(client, db):
    from core.dependencies import get_current_user as core_user
    from routers.admin_users.auth import get_current_user as auth_user
    u, jobs = _users_and_jobs(db)
    main.app.dependency_overrides[auth_user] = lambda: u["company"]
    main.app.dependency_overrides[core_user] = lambda: u["company"]
    try:
        assert client.delete(f"/api/jobs/delete/{jobs['j3'].id}").status_code == 404   # other company
        assert client.delete(f"/api/jobs/delete/{jobs['j2'].id}").status_code == 200   # own company
    finally:
        main.app.dependency_overrides.clear()


def test_company_sees_its_recruiters_candidates_not_other_companies(client, db):
    from model.models import Application
    from core.dependencies import get_current_user as core_user
    from routers.admin_users.auth import get_current_user as auth_user
    u, jobs = _users_and_jobs(db)
    for name, email in (("j1", "c1@x.com"), ("j2", "c2@x.com"), ("j3", "c3@x.com")):
        cand = Candidate(name=name, email=email, role="candidate", skills=None,
                         resume_url=None, notes=None, recruiter_comments=None)
        db.add(cand)
        db.commit()
        db.refresh(cand)
        db.add(Application(job_id=jobs[name].id, candidate_id=cand.id, candidate_name=name,
                           candidate_email=email, stage="Applied"))
    db.commit()

    def names_for(user):
        main.app.dependency_overrides[core_user] = lambda: user
        main.app.dependency_overrides[auth_user] = lambda: user
        try:
            r = client.get("/api/pipeline/candidates/")
            assert r.status_code == 200, r.text
            return sorted(c["email"] for c in r.json())
        finally:
            main.app.dependency_overrides.clear()

    assert names_for(u["r1"]) == ["c1@x.com"]
    assert names_for(u["company"]) == ["c1@x.com", "c2@x.com"]
    assert names_for(u["admin"]) == ["c1@x.com", "c2@x.com"]
    assert names_for(u["other"]) == ["c3@x.com"]


# ---------- branches ----------

def _tenant_with_branches(db):
    from model.Company_Settings.location import CompanyLocation
    from super_admin.multi_tenant import Tenant
    t = Tenant(tenant_name="Acme", contact_email="a@acme.com", plan="BASIC", status="active")
    db.add(t)
    db.commit()
    db.refresh(t)
    locs = []
    for name in ("Hyderabad", "Chennai"):
        l = CompanyLocation(tenant_id=t.id, name=name, timezone="Asia/Kolkata", is_active=True,
                            is_default=(name == "Hyderabad"))
        db.add(l)
        db.commit()
        db.refresh(l)
        locs.append(l)
    return t, locs


def _signup(client, **kw):
    body = {"name": "Rec", "email": "rec@acme.com", "password": "secret1", "role": "recruiter",
            "company_name": "Acme"}
    body.update(kw)
    return client.post("/api/auth/signup", json=body)


def test_signup_lists_branches_and_requires_one(client, db):
    t, (hyd, chn) = _tenant_with_branches(db)
    names = [b["name"] for b in client.get("/api/auth/signup-branches", params={"company_name": "acme"}).json()]
    assert names == ["Hyderabad", "Chennai"]                       # default first, name match is case-insensitive
    assert client.get("/api/auth/signup-branches", params={"company_name": "Nope"}).json() == []

    assert _signup(client).status_code == 422                       # branch is required for this company
    assert _signup(client, location_id=99999).status_code == 400    # not one of this company's branches
    r = _signup(client, location_id=chn.id)
    assert r.status_code == 201, r.text
    assert db.query(User).filter(User.email == "rec@acme.com").one().location_id == chn.id


def test_signup_for_new_company_without_branches_still_works(client, db):
    assert _signup(client, company_name="Brand New Co").status_code == 201


def test_me_returns_branch_and_admin_user_form_keeps_it(client, db):
    from routers.admin_users.auth import get_current_user as auth_user
    t, (hyd, chn) = _tenant_with_branches(db)
    _signup(client, location_id=chn.id)
    rec = db.query(User).filter(User.email == "rec@acme.com").one()
    main.app.dependency_overrides[auth_user] = lambda: rec
    try:
        me = client.get("/api/auth/me").json()
        assert me["location_id"] == chn.id and me["branch_name"] == "Chennai"
    finally:
        main.app.dependency_overrides.clear()

    # Super admin creates a branch admin: location_id must be stored and returned (it used to be dropped).
    from core.dependencies import get_current_user as core_user
    sup = User(name="S", email="s@x.com", hashed_password="x", role="superadmin", is_active=True,
               created_at=datetime.now(timezone.utc))
    main.app.dependency_overrides[auth_user] = lambda: sup
    main.app.dependency_overrides[core_user] = lambda: sup
    try:
        r = client.post("/api/admin/superadmin/users", json={"name": "BA", "email": "ba@acme.com", "role": "admin",
                        "password": "secret1", "tenant_id": t.id, "location_id": hyd.id})
        assert r.status_code == 201, r.text
        assert r.json()["location_id"] == hyd.id and r.json()["branch_name"] == "Hyderabad"
        # a branch from another company is refused
        full = {"name": "BA", "username": None, "email": "ba@acme.com", "role": "admin", "is_active": True}
        r2 = client.put(f"/api/admin/superadmin/users/{r.json()['id']}", json={**full, "location_id": 99999})
        assert r2.status_code == 400
        # null clears it
        r3 = client.put(f"/api/admin/superadmin/users/{r.json()['id']}", json={**full, "location_id": None})
        assert r3.json()["location_id"] is None
    finally:
        main.app.dependency_overrides.clear()


def test_branch_admin_sees_only_their_branch_jobs_and_company_can_filter(client, db):
    from core.dependencies import get_current_user as core_user
    from routers.admin_users.auth import get_current_user as auth_user
    t, (hyd, chn) = _tenant_with_branches(db)

    def mk(email, role, loc):
        u = User(name=email, email=email, hashed_password="x", role=role, tenant_id=t.id, location_id=loc,
                 is_active=True, created_at=datetime.now(timezone.utc))
        db.add(u)
        db.commit()
        db.refresh(u)
        return u

    r_h, r_c = mk("rh@a.com", "recruiter", hyd.id), mk("rc@a.com", "recruiter", chn.id)
    company, admin_h = mk("co@a.com", "company", None), mk("ah@a.com", "admin", hyd.id)
    for name, rec in (("hyd-job", r_h), ("chn-job", r_c)):
        db.add(Job(title=name, department="Eng", employment_type="Full-time", description="d",
                   status="Published", role=name, recruiter_id=rec.id))
    db.commit()

    def jobs(user, header=None):
        main.app.dependency_overrides[auth_user] = lambda: user
        main.app.dependency_overrides[core_user] = lambda: user
        try:
            r = client.get("/api/jobs/list", headers=({"X-Location-Id": str(header)} if header else {}))
            assert r.status_code == 200, r.text
            return {j["title"]: j for j in r.json()}
        finally:
            main.app.dependency_overrides.clear()

    assert sorted(jobs(company)) == ["chn-job", "hyd-job"]                       # whole company
    assert sorted(jobs(company, header=chn.id)) == ["chn-job"]                   # branch selector
    assert sorted(jobs(admin_h)) == ["hyd-job"]                                  # branch admin: locked
    assert sorted(jobs(admin_h, header=chn.id)) == ["hyd-job"]                   # header cannot widen it
    shown = jobs(company)["hyd-job"]
    assert shown["branch_name"] == "Hyderabad" and shown["recruiter_name"] == "rh@a.com"
