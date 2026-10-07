"""
Aptitude Test Results API
Provides endpoints to fetch test results from the aptitude_assessment_results table
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from core.database import get_db
from model.models import LegacyCandidate as Candidate, User, Job, Application
from core.dependencies import get_current_user
from sqlmodel import select
from core.job_access import sees_all_jobs, visible_jobs_clause
from typing import List, Optional

router = APIRouter(prefix="/results", tags=["Aptitude Results"])

@router.get("/all")
def get_all_results(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Get all aptitude test results filtered by recruiter"""
    
    recruiter_candidate_emails = set()
    
    if not sees_all_jobs(user):
        
        job_ids = list(db.exec(select(Job.id).where(visible_jobs_clause(user))).all())
        
        if job_ids:
            
            applications = db.exec(select(Application).where(Application.job_id.in_(job_ids))).all()
            
            for app in applications:
                if app.candidate_email:
                    recruiter_candidate_emails.add(app.candidate_email.lower().strip())
            
            
            candidate_ids = list(set([app.candidate_id for app in applications if app.candidate_id]))
            if candidate_ids:
                from model.models import Candidate as CandidateModel
                candidates = db.exec(select(CandidateModel).where(CandidateModel.id.in_(candidate_ids))).all()
                for candidate in candidates:
                    if candidate.email:
                        recruiter_candidate_emails.add(candidate.email.lower().strip())
    
   
    query = db.query(Candidate).filter(Candidate.verified == 1)
    
   
    if not sees_all_jobs(user) and recruiter_candidate_emails:
        from sqlalchemy import func
        query = query.filter(
            func.lower(func.trim(Candidate.email)).in_(
                [email.lower().strip() for email in recruiter_candidate_emails]
            )
        )
    
    candidates = query.all()
    
    results = []
    for candidate in candidates:
        results.append({
            "id": candidate.id,
            "name": candidate.name,
            "email": candidate.email,
            "score": candidate.score,
            "status": candidate.status,
            "total_questions": 25,
            "percentage": round((candidate.score / 25) * 100, 2) if candidate.score else 0
        })
    
    return results

@router.get("/by-email/{email}")
def get_result_by_email(email: str, db: Session = Depends(get_db)):
    """Get test result by candidate email"""
    candidate = db.query(Candidate).filter(Candidate.email == email).first()
    
    if not candidate:
        return {"message": "No test result found for this email"}
    
    return {
        "id": candidate.id,
        "name": candidate.name,
        "email": candidate.email,
        "score": candidate.score,
        "status": candidate.status,
        "total_questions": 25,
        "percentage": round((candidate.score / 25) * 100, 2) if candidate.score else 0,
        "answers": candidate.answers if hasattr(candidate, 'answers') else {}
    }

@router.get("/by-id/{candidate_id}")
def get_result_by_id(candidate_id: int, db: Session = Depends(get_db)):
    """Get test result by candidate ID"""
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    
    if not candidate:
        return {"message": "No test result found"}
    
    return {
        "id": candidate.id,
        "name": candidate.name,
        "email": candidate.email,
        "score": candidate.score,
        "status": candidate.status,
        "total_questions": 25,
        "percentage": round((candidate.score / 25) * 100, 2) if candidate.score else 0,
        "answers": candidate.answers if hasattr(candidate, 'answers') else {}
    }

@router.get("/statistics")
def get_statistics(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Get overall aptitude test statistics filtered by recruiter"""
    
    recruiter_candidate_emails = set()
    
    if not sees_all_jobs(user):
        job_ids = list(db.exec(select(Job.id).where(visible_jobs_clause(user))).all())
        if job_ids:
            applications = db.exec(select(Application).where(Application.job_id.in_(job_ids))).all()
            for app in applications:
                if app.candidate_email:
                    recruiter_candidate_emails.add(app.candidate_email.lower().strip())
            candidate_ids = list(set([app.candidate_id for app in applications if app.candidate_id]))
            if candidate_ids:
                from model.models import Candidate as CandidateModel
                candidates = db.exec(select(CandidateModel).where(CandidateModel.id.in_(candidate_ids))).all()
                for candidate in candidates:
                    if candidate.email:
                        recruiter_candidate_emails.add(candidate.email.lower().strip())
    
    query = db.query(Candidate).filter(Candidate.verified == 1)
    if not sees_all_jobs(user) and recruiter_candidate_emails:
        from sqlalchemy import func
        query = query.filter(
            func.lower(func.trim(Candidate.email)).in_(
                [email.lower().strip() for email in recruiter_candidate_emails]
            )
        )
    
    all_candidates = query.all()
    
    if not all_candidates:
        return {
            "total_tests": 0,
            "passed": 0,
            "failed": 0,
            "average_score": 0,
            "pass_rate": 0
        }
    
    total = len(all_candidates)
    passed = len([c for c in all_candidates if c.status == "Qualified"])
    failed = len([c for c in all_candidates if c.status == "Regret"])
    avg_score = sum([c.score for c in all_candidates]) / total if total > 0 else 0
    pass_rate = (passed / total * 100) if total > 0 else 0
    
    return {
        "total_tests": total,
        "passed": passed,
        "failed": failed,
        "average_score": round(avg_score, 2),
        "pass_rate": round(pass_rate, 2)
    }



