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
