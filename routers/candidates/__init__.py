from fastapi import APIRouter
from . import Applications, Profile, JobSearch, SavedJobs, RecentApplications, RecommendedJobSections, Notifications, Apply

# Main router for candidates
router = APIRouter(prefix="/api/candidates", tags=["candidates"])

# Sub-routers: each one already declares its own prefix (/applications, /profile,
# /saved-jobs, ...). Do NOT add a second prefix here or the final URL doubles up
# (e.g. /api/candidates/applications/applications/). Apply has no prefix of its own.
router.include_router(Applications.router)
router.include_router(Profile.router)
router.include_router(JobSearch.router)
router.include_router(SavedJobs.router)
router.include_router(RecentApplications.router)
router.include_router(RecommendedJobSections.router)
router.include_router(Notifications.router)
router.include_router(Apply.router, prefix="/apply")
