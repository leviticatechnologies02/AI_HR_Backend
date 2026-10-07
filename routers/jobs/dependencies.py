from fastapi import Depends, HTTPException
from typing import List
from model.models import User
from routers.admin_users.auth import get_current_user

def require_roles(allowed_roles: List[str]):
    def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role.lower() not in [r.lower() for r in allowed_roles]:
            raise HTTPException(status_code=403, detail="Operation not permitted")
        return current_user
    return role_checker


from core.job_access import visible_jobs_clause, sees_all_jobs  # noqa: F401  (single shared rule)

# Roles that may view and manage jobs.
JOB_VIEW_ROLES = ["recruiter", "company", "admin", "hr_admin", "superadmin"]
