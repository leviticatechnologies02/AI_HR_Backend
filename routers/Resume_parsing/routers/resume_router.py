import os
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse
from pydantic import BaseModel
from openai import AuthenticationError as OpenAIAuthError, APIError as OpenAIAPIError
from typing import Optional

from core.database import SessionLocal, init_db
from model.models import CandidateRecord, Candidate, Application, LegacyCandidate, Job, User
from routers.Resume_parsing.routers.utils import extract_text, ai_extract_fields, ai_generate_jd, ai_similarity_score, send_email_smtp
from routers.Resume_parsing.routers.config import SCORE_THRESHOLD
from routers.Candidate_assessments.Assessment.utils.stage_sync import update_candidate_stage_all_tables
from sqlmodel import select
from sqlalchemy import text, func
from core.dependencies import get_current_user
from core.job_access import see_all_jobs, visible_jobs_clause

class StageUpdate(BaseModel):
    stage: str

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/")
def root():
    return {"status": "ok"}


@router.get("/screening-config")
def get_screening_config(user: User = Depends(get_current_user)):
    return {"score_threshold": SCORE_THRESHOLD}


@router.get("/candidates")
def list_candidates(
    db: Session = Depends(get_db), 
    limit: int = 1000, 
    offset: int = 0,
    user: User = Depends(get_current_user),
    show_all: bool = Query(False, description="If True, show all screened candidates regardless of aptitude completion")
):
    recruiter_candidate_emails = set()
    recruiter_has_jobs = False
    
    if not sees_all_jobs(user):
        # Job IDs visible to this user (own jobs, or their company's jobs)
        job_ids = [row[0] for row in db.execute(select(Job.id).where(visible_jobs_clause(user))).all()]
        print(f" Recruiter {user.id} has {len(job_ids)} jobs")
        recruiter_has_jobs = len(job_ids) > 0
        
        if job_ids:
            
            applications = db.execute(select(Application).where(Application.job_id.in_(job_ids))).scalars().all()
            print(f" Found {len(applications)} applications for recruiter's jobs")
            
            for app in applications:
                if app.candidate_email:
                    recruiter_candidate_emails.add(app.candidate_email.lower().strip())
            
            
            candidate_ids = list(set([app.candidate_id for app in applications if app.candidate_id]))
            if candidate_ids:
                candidates = db.execute(select(Candidate).where(Candidate.id.in_(candidate_ids))).scalars().all()
                for candidate in candidates:
                    if candidate.email:
                        recruiter_candidate_emails.add(candidate.email.lower().strip())
        
        print(f" Recruiter {user.id} has {len(recruiter_candidate_emails)} unique candidate emails from applications")
    
    
    query = db.query(CandidateRecord).order_by(CandidateRecord.id.desc())
    
    
    if not sees_all_jobs(user):
        if recruiter_candidate_emails:
            
            query = query.filter(
                func.lower(func.trim(CandidateRecord.candidate_email)).in_(
                    [email.lower().strip() for email in recruiter_candidate_emails]
                )
            )
            print(f"🔍 Filtering candidate_records by {len(recruiter_candidate_emails)} emails from applications")
        elif recruiter_has_jobs:
            
            query = query.filter(CandidateRecord.resume_screened == "yes")
            print(f" Recruiter {user.id} has jobs but no applications - showing all screened candidates (resume_screened='yes')")
        else:
            
            print(f" Recruiter {user.id} has no jobs, returning empty result")
            return []
    
    rows = query.offset(offset).limit(limit).all()
    print(f" Found {len(rows)} candidate_records after filtering")
    
    completed_aptitude_emails = set()
    if not show_all:
        try:
            aptitude_completed = db.query(LegacyCandidate).filter(
                LegacyCandidate.status.isnot(None),
                LegacyCandidate.status != '',
                LegacyCandidate.status.in_(['Qualified', 'Regret', 'Completed', 'Passed', 'Submitted'])
            ).all()
            completed_aptitude_emails = {c.email.lower() for c in aptitude_completed if c.email}
            print(f" Found {len(completed_aptitude_emails)} candidates who completed aptitude test")
        except Exception as e:
            print(f" Warning: Could not check aptitude completion status: {e}")
    else:
        print(f" show_all=True: Showing all screened candidates regardless of aptitude completion")
    
    result = []
    for r in rows:
       
        stage_value = None
        if hasattr(r, 'stage'):
            stage_value = r.stage
        if not stage_value or stage_value == '':
            stage_value = "Applied"  
       
        if not show_all:
            
            candidate_stage_lower = stage_value.lower() if stage_value else ''
            is_advanced_stage = candidate_stage_lower in ['interview', 'offer', 'hired']
            
            
            if r.candidate_email and r.candidate_email.lower() in completed_aptitude_emails and not is_advanced_stage:
                continue
        
        result.append({
            "id": r.id, 
            "candidate_name": r.candidate_name,
            "candidate_email": r.candidate_email,
            "candidate_skills": r.candidate_skills,
            "role": r.role, 
            "experience_level": r.experience_level,
            "score": r.score, 
            "threshold": SCORE_THRESHOLD,
            "email_sent": r.email_sent,
            "resume_screened": getattr(r, 'resume_screened', 'no'),  # Include resume_screened field
            "stage": stage_value,  # Include stage field
            "created_at": r.created_at.isoformat() if r.created_at else None
        })
    
    print(f" Returning {len(result)} candidate records (after filtering aptitude completed)")
    print(f" Breakdown: Total rows={len(rows)}, Filtered out={len(rows) - len(result)}, Final result={len(result)}")
    return result

@router.patch("/candidates/{candidate_id}/stage")
def update_candidate_stage_endpoint(
    candidate_id: int,
    payload: StageUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
   
    try:
        
        candidate_record = db.query(CandidateRecord).filter(CandidateRecord.id == candidate_id).first()
        if not candidate_record:
            raise HTTPException(status_code=404, detail="Candidate not found")
        
        if candidate_record.candidate_email:
            success = update_candidate_stage_all_tables(db, candidate_record.candidate_email, payload.stage)
            if success:
                return JSONResponse({
                    "success": True,
                    "message": f"Stage updated to '{payload.stage}' for candidate {candidate_record.candidate_name}",
                    "candidate_id": candidate_id,
                    "email": candidate_record.candidate_email,
                    "new_stage": payload.stage
                })
            else:
                raise HTTPException(status_code=500, detail="Failed to update candidate stage")
        else:
            raise HTTPException(status_code=400, detail="Candidate email not found")
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating candidate stage: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error updating candidate stage: {str(e)}")

@router.post("/sync-stages")
def sync_candidate_stages_endpoint(db: Session = Depends(get_db)):
    
    try:
        print("=" * 60)
        print("Syncing Candidate Stages Based on Scores")
        print("=" * 60)
        print(f"Score Threshold: {SCORE_THRESHOLD}")
        print()
        
       
        print(" Updating candidate_records stages...")
        update_records_query = text("""
            UPDATE candidate_records 
            SET stage = CASE 
                WHEN score IS NULL THEN 'Applied'
                WHEN score < :threshold THEN 'Rejected'
                ELSE 'Screening'
            END
            WHERE (stage IS NULL 
               OR (score IS NOT NULL AND score < :threshold AND stage NOT IN ('Screening', 'Interview', 'Offer', 'Hired') AND stage != 'Rejected')
               OR (score IS NOT NULL AND score >= :threshold AND stage IN ('Rejected', 'Applied') AND stage NOT IN ('Screening', 'Interview', 'Offer', 'Hired')))
        """)
        
        result = db.execute(update_records_query, {"threshold": SCORE_THRESHOLD})
        db.commit()
        records_updated = result.rowcount
        print(f" Updated {records_updated} candidate_records")
        
        
        print("\\ Syncing candidate table stages from candidate_records...")
        sync_candidates_query = text("""
            UPDATE candidate c
            SET stage = cr.stage
            FROM candidate_records cr
            WHERE LOWER(TRIM(c.email)) = LOWER(TRIM(cr.candidate_email))
              AND cr.stage IS NOT NULL
              AND (c.stage IS NULL 
                   OR (c.stage NOT IN ('Screening', 'Interview', 'Offer', 'Hired') AND c.stage != cr.stage))
        """)
        
        result = db.execute(sync_candidates_query)
        db.commit()
        candidates_updated = result.rowcount
        print(f" Updated {candidates_updated} candidate records")
        
        
        print("\n Syncing application table stages from candidate_records...")
        sync_applications_from_records_query = text("""
            UPDATE application a
            SET stage = cr.stage,
                updated_at = CURRENT_TIMESTAMP
            FROM candidate_records cr
            WHERE LOWER(TRIM(a.candidate_email)) = LOWER(TRIM(cr.candidate_email))
              AND cr.stage IS NOT NULL
              AND (a.stage IS NULL 
                   OR (a.stage NOT IN ('Screening', 'Interview', 'Offer', 'Hired') AND a.stage != cr.stage))
        """)
        
        result = db.execute(sync_applications_from_records_query)
        db.commit()
        applications_from_records_updated = result.rowcount
        print(f" Updated {applications_from_records_updated} application records from candidate_records")
        
        
        print("\n Syncing application table stages from candidate table...")
        sync_applications_from_candidate_query = text("""
            UPDATE application a
            SET stage = c.stage,
                updated_at = CURRENT_TIMESTAMP
            FROM candidate c
            WHERE a.candidate_id = c.id
              AND c.stage IS NOT NULL
              AND (a.stage IS NULL 
                   OR (a.stage NOT IN ('Screening', 'Interview', 'Offer', 'Hired') AND a.stage != c.stage))
        """)
        
        result = db.execute(sync_applications_from_candidate_query)
        db.commit()
        applications_from_candidate_updated = result.rowcount
        print(f" Updated {applications_from_candidate_updated} application records from candidate table")
        
        
        print("\n Current Statistics:")
        
      
        stats_query = text("""
            SELECT 
                stage,
                COUNT(*) as count,
                AVG(score) as avg_score,
                COUNT(CASE WHEN score IS NULL THEN 1 END) as null_scores
            FROM candidate_records
            GROUP BY stage
            ORDER BY stage
        """)
        
        stats = db.execute(stats_query).fetchall()
        stats_list = []
        for stage, count, avg_score, null_scores in stats:
            avg_str = f"{avg_score:.2f}" if avg_score else "N/A"
            null_str = f" ({null_scores} NULL scores)" if null_scores > 0 else ""
            stats_list.append({
                "stage": stage,
                "count": count,
                "avg_score": float(avg_score) if avg_score else None,
                "null_scores": null_scores
            })
        
        return JSONResponse({
            "success": True,
            "message": "Stages synced successfully",
            "records_updated": records_updated,
            "candidates_updated": candidates_updated,
            "applications_from_records_updated": applications_from_records_updated,
            "applications_from_candidate_updated": applications_from_candidate_updated,
            "statistics": stats_list
        })
        
    except Exception as e:
        print(f"\n Error during sync: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "message": f"Error syncing stages: {str(e)}"
        }, status_code=500)

@router.post("/process")
async def process_resume(
    file: UploadFile = File(...),
    role: str = Form(...),
    experience_level: str = Form(...),
    candidate_id: Optional[int] = Form(None),
    candidate_email: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
   
    content = await file.read()
    try:
        resume_text = extract_text(file.filename, content)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    
    try:
        fields = ai_extract_fields(resume_text)
    except OpenAIAuthError as e:
        raise HTTPException(
            status_code=503,
            detail="AI resume screening is unavailable: invalid or missing OpenAI API key. Please set OPENAI_API_KEY in the server environment."
        )
    except OpenAIAPIError as e:
        raise HTTPException(
            status_code=503,
            detail=f"AI service error: {getattr(e, 'message', str(e))}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"AI resume screening failed: {str(e)}"
        )

    name, email, skills, exp_summary = (
        fields["name"], fields["email"], fields["skills"], fields["experience_summary"]
    )

    canonical_email = (candidate_email or "").strip() or (email or "").strip()
    if candidate_id is not None:
        try:
            candidate_row = db.get(Candidate, candidate_id)
            if candidate_row and candidate_row.email:
                canonical_email = candidate_row.email.strip()
        except Exception as e:
            print(f"Warning: Could not resolve canonical email from candidate_id={candidate_id}: {e}")

    duplicate_keys = []
    if canonical_email:
        duplicate_keys.append(canonical_email.lower().strip())
    if email:
        extracted_email = email.lower().strip()
        if extracted_email and extracted_email not in duplicate_keys:
            duplicate_keys.append(extracted_email)

    if duplicate_keys:
        try:
            existing_record = db.query(CandidateRecord).filter(
                func.lower(func.trim(CandidateRecord.candidate_email)).in_(duplicate_keys),
                CandidateRecord.resume_screened == "yes"
            ).first()
            if existing_record:
                duplicate_email = existing_record.candidate_email or canonical_email or email
                raise HTTPException(
                    status_code=400,
                    detail=f"Resume for {duplicate_email} has already been screened. Cannot screen again."
                )
        except HTTPException:
            raise
        except Exception as e:
            if "resume_screened" in str(e) or "does not exist" in str(e):
                print(f" Warning: resume_screened column may not exist yet: {e}")
            else:
                raise

    try:
        jd_text = ai_generate_jd(role, experience_level)
    except (OpenAIAuthError, OpenAIAPIError) as e:
        raise HTTPException(
            status_code=503,
            detail="AI resume screening is unavailable. Please check OpenAI API key configuration."
        )

   
    try:
        score = ai_similarity_score(resume_text, jd_text)
    except (OpenAIAuthError, OpenAIAPIError) as e:
        raise HTTPException(
            status_code=503,
            detail="AI resume screening is unavailable. Please check OpenAI API key configuration."
        )
    
   
    if score is None:
        score = 0.0
        print(f" Warning: Score was None for {email}, setting to 0.0")

    email_status = "skipped"
    save_path = os.path.join("uploads", file.filename)
    os.makedirs("uploads", exist_ok=True)
    with open(save_path, "wb") as f:
        f.write(content)

    initial_stage = "Rejected" if score < SCORE_THRESHOLD else "Screening"
    
    rec_data = {
        "role": role,
        "experience_level": experience_level,
        "candidate_name": name,
        "candidate_email": canonical_email or email,
        "candidate_skills": ", ".join(skills) if isinstance(skills, list) else str(skills),
        "candidate_experience_text": exp_summary,
        "resume_text": resume_text[:25000],
        "jd_text": jd_text[:25000],
        "score": score,
        "resume_filename": file.filename,
        "email_sent": "no",
        "stage": initial_stage
    }
   
    if hasattr(CandidateRecord, 'resume_screened'):
        rec_data["resume_screened"] = "yes"  
    
    rec = CandidateRecord(**rec_data)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    rec_id = rec.id

    
    candidate_for_list = None
    sync_email = None

    if candidate_id is not None:
        try:
            candidate_for_list = db.get(Candidate, candidate_id)
            if candidate_for_list:
                candidate_for_list.stage = initial_stage
                candidate_for_list.role = role
                candidate_for_list.skills = ", ".join(skills) if isinstance(skills, list) else str(skills)
                if file.filename:
                    candidate_for_list.resume_url = candidate_for_list.resume_url or f"uploads/{file.filename}"
                db.add(candidate_for_list)
                db.commit()
                print(f" Updated Candidate(id={candidate_id}).stage to '{initial_stage}'")
                sync_email = candidate_for_list.email
        except Exception as e:
            print(f"Warning: Could not update Candidate by candidate_id={candidate_id}: {e}")

    
    if not sync_email and email:
        try:
            email_normalized = email.lower().strip()

            try:
                statement = select(Candidate).where(func.lower(func.trim(Candidate.email)) == email_normalized)
                candidate = db.exec(statement).first()
            except AttributeError:
                candidate = db.query(Candidate).filter(
                    func.lower(func.trim(Candidate.email)) == email_normalized
                ).first()

            if not candidate:
                candidate = Candidate(
                    name=name,
                    email=email,
                    role=role,
                    skills=", ".join(skills) if isinstance(skills, list) else str(skills),
                    stage=initial_stage,
                    resume_url=f"uploads/{file.filename}" if file.filename else None
                )
                db.add(candidate)
                db.commit()
                print(f" Created Candidate record for {email} with stage '{initial_stage}'")
            else:
                candidate.stage = initial_stage
                candidate.role = role
                candidate.skills = ", ".join(skills) if isinstance(skills, list) else str(skills)
                if not candidate.resume_url and file.filename:
                    candidate.resume_url = f"uploads/{file.filename}"
                db.add(candidate)
                db.commit()
                print(f" Updated Candidate.stage to '{initial_stage}' for {email}")

            sync_email = candidate.email
        except Exception as e:
            print(f"Warning: Could not create/update Candidate record by extracted email: {e}")
            import traceback
            traceback.print_exc()

   
    if not sync_email and candidate_email:
        sync_email = candidate_email
    
    
    if score >= SCORE_THRESHOLD and (sync_email or email):
        ok, msg = send_email_smtp(name, email, score, role)
        rec.email_sent = "yes" if ok else f"error: {msg}"
        rec.stage = "Screening"  # Ensure stage is "Screening" for shortlisted
        db.add(rec)
        db.commit()
        email_status = rec.email_sent
        
        try:
            if sync_email:
                update_candidate_stage_all_tables(db, sync_email, "Screening")
            elif email:
                update_candidate_stage_all_tables(db, email, "Screening")
        except Exception as e:
            print(f"Warning: Could not update candidate stage: {e}")
    elif score < SCORE_THRESHOLD:
        
        email_status = "not_sent_rejected"
       
        rec.stage = "Rejected"
        db.add(rec)
        db.commit()
       
        try:
            if sync_email:
                update_candidate_stage_all_tables(db, sync_email, "Rejected")
            elif email:
                update_candidate_stage_all_tables(db, email, "Rejected")
        except Exception as e:
            print(f"Warning: Could not update candidate stage: {e}")
        
        
        try:
            stage_email = sync_email or email
            if stage_email:
              
                try:
                    result = db.execute(
                        text("""
                            UPDATE application 
                            SET stage = 'Rejected',
                                updated_at = CURRENT_TIMESTAMP
                            WHERE (candidate_email = :email OR candidate_id IN (
                                SELECT id FROM candidate WHERE email = :email
                            ))
                            AND (stage = 'Applied' OR stage IS NULL)
                        """),
                        {"email": stage_email}
                    )
                    db.commit()
                    sql_updated = result.rowcount
                    if sql_updated > 0:
                        print(f" Updated {sql_updated} Application record(s) to 'Rejected' for {stage_email}")
                except Exception as sql_error:
                    print(f"Warning: SQL update failed: {sql_error}")
                    
                    try:
                        
                        candidate = None
                        try:
                            statement = select(Candidate).where(Candidate.email == stage_email)
                            candidate = db.exec(statement).first()
                        except AttributeError:
                            candidate = db.query(Candidate).filter(Candidate.email == stage_email).first()
                        
                        updated_apps = set()  
                        
                       
                        if candidate:
                            applications = db.query(Application).filter(
                                Application.candidate_id == candidate.id
                            ).all()
                            
                            for app in applications:
                                if (app.stage == "Applied" or app.stage is None):
                                    app.stage = "Rejected"
                                    db.add(app)
                                    updated_apps.add(app.id)
                        
                        
                        applications_by_email = db.query(Application).filter(
                            Application.candidate_email == stage_email
                        ).all()
                        
                        for app in applications_by_email:
                            if app.id not in updated_apps:
                                if (app.stage == "Applied" or app.stage is None):
                                    app.stage = "Rejected"
                                    db.add(app)
                                    updated_apps.add(app.id)
                        
                        if updated_apps:
                            db.commit()
                            print(f" Updated {len(updated_apps)} Application record(s) to 'Rejected' for {stage_email} (ORM fallback)")
                    except Exception as orm_error:
                        print(f"Warning: ORM update also failed: {orm_error}")
                    
        except Exception as e:
            print(f"Warning: Could not update Application records: {e}")
            import traceback
            traceback.print_exc()
    else:
        email_status = "no_email_provided"

    return JSONResponse({
        "id": rec_id,
        "role": role,
        "experience_level": experience_level,
        "candidate": {"name": name, "email": email, "skills": skills, "experience_summary": exp_summary},
        "jd_preview": jd_text[:600],
        "score": score,
        "threshold": SCORE_THRESHOLD,
        "status": "shortlisted" if score >= SCORE_THRESHOLD else "rejected",
        "email_status": email_status
    })
