from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import select
from pydantic import BaseModel, EmailStr
from typing import Optional
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import jwt, JWTError

from core.database import get_db
from core.config import settings
from model.models import Candidate

router = APIRouter(tags=["Candidate Auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = settings.SECRET_KEY   # from .env, never hard-coded
ALGORITHM = "HS256"

class CandidateSignup(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: Optional[str] = "candidate"
    source: Optional[str] = "Unknown"  # LinkedIn | Referral | Naukri | Career Page | Unknown

class CandidateLogin(BaseModel):
    email: EmailStr
    password: str

class CandidateTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    candidate_id: int
    name: str
    email: str

def create_candidate_token(candidate_id: int) -> str:
    expire = datetime.utcnow() + timedelta(hours=24)
    return jwt.encode({"sub": str(candidate_id), "type": "candidate", "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

@router.post("/signup", status_code=201)
def candidate_signup(payload: CandidateSignup, db: Session = Depends(get_db)):
    existing = db.execute(select(Candidate).where(Candidate.email == payload.email)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    candidate = Candidate(
        name=payload.name,
        email=payload.email,
        hashed_password=pwd_context.hash(payload.password),
        role=payload.role or "candidate",
        source=payload.source or "Unknown",
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return {"message": "Registration successful. You can now log in."}

@router.post("/login", response_model=CandidateTokenResponse)
def candidate_login(payload: CandidateLogin, db: Session = Depends(get_db)):
    candidate = db.execute(select(Candidate).where(Candidate.email == payload.email)).scalar_one_or_none()
    if not candidate or not hasattr(candidate, 'hashed_password'):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not pwd_context.verify(payload.password, candidate.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_candidate_token(candidate.id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "candidate_id": candidate.id,
        "name": candidate.name,
        "email": candidate.email,
    }


# ---------------------------------------------------------------------------
# Shared dependency for any candidate-facing route that needs to know who's
# calling (e.g. Apply). Decodes the "candidate"-typed JWT issued by /login
# above and loads the matching Candidate row.
# ---------------------------------------------------------------------------
_candidate_bearer = HTTPBearer(auto_error=False)


def get_current_candidate(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_candidate_bearer),
    db: Session = Depends(get_db),
) -> Candidate:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if payload.get("type") != "candidate":
        raise HTTPException(status_code=401, detail="Not a candidate token")

    candidate_id = payload.get("sub")
    if candidate_id is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    candidate = db.get(Candidate, int(candidate_id))
    if not candidate:
        raise HTTPException(status_code=401, detail="Candidate not found")

    return candidate
