from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.database import get_db
from model.models import Candidate
from .auth import get_current_candidate

router = APIRouter(prefix="/profile", tags=["Profile"])


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    skills: Optional[str] = None


def _out(c: Candidate) -> dict:
    return {"id": c.id, "name": c.name, "email": c.email, "role": c.role or "", "skills": c.skills or ""}


@router.get("/")
def read_profile(candidate: Candidate = Depends(get_current_candidate)):
    """Profile of the logged-in candidate (candidate-portal token)."""
    return _out(candidate)


@router.post("/")
@router.put("/")
def save_profile(
    payload: ProfileUpdate,
    candidate: Candidate = Depends(get_current_candidate),
    db: Session = Depends(get_db),
):
    for field in ("name", "role", "skills"):
        val = getattr(payload, field)
        if val is not None:
            setattr(candidate, field, val)
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return _out(candidate)
