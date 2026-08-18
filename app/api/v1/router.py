from fastapi import APIRouter

from app.api.v1 import (
    audit_logs,
    auth,
    invitations,
    memberships,
    organizations,
    projects,
    sessions,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(memberships.router)
api_router.include_router(invitations.router)
api_router.include_router(projects.router)
api_router.include_router(sessions.router)
api_router.include_router(audit_logs.router)
