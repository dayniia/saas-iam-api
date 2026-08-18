from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_permission
from app.database import get_db
from app.models.membership import OrgMembership
from app.schemas.audit_log import AuditLogListResponse, AuditLogResponse
from app.services import audit_service

router = APIRouter(prefix="/orgs/{org_id}/audit-logs", tags=["Audit Logs"])


@router.get(
    "",
    response_model=AuditLogListResponse,
    summary="Query audit logs",
    description="Paginated audit log for the organization. Requires audit.read.",
)
async def list_logs(
    org_id: UUID,
    _membership: Annotated[OrgMembership, Depends(require_permission("audit.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AuditLogListResponse:
    items, total = await audit_service.list_audit_logs(
        db, organization_id=org_id, page=page, page_size=page_size
    )
    return AuditLogListResponse(
        items=[
            AuditLogResponse(
                id=e.id,
                organization_id=e.organization_id,
                actor_id=e.actor_id,
                action=e.action,
                resource_type=e.resource_type,
                resource_id=e.resource_id,
                metadata=e.metadata_,
                created_at=e.created_at,
            )
            for e in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
