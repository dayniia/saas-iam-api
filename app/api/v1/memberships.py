from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_permission
from app.database import get_db
from app.models.membership import OrgMembership
from app.schemas.membership import MembershipResponse, MembershipRoleUpdate
from app.services import org_service

router = APIRouter(prefix="/orgs/{org_id}/members", tags=["Memberships"])


def _to_response(m: OrgMembership) -> MembershipResponse:
    return MembershipResponse(
        id=m.id,
        organization_id=m.organization_id,
        user_id=m.user_id,
        role_id=m.role_id,
        role_name=m.role.name if m.role else None,
        user_email=m.user.email if m.user else None,
        user_full_name=m.user.full_name if m.user else None,
        created_at=m.created_at,
    )


@router.get(
    "",
    response_model=list[MembershipResponse],
    summary="List members",
    description="List organization members. Requires users.read.",
)
async def list_members(
    org_id: UUID,
    _membership: Annotated[OrgMembership, Depends(require_permission("users.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[MembershipResponse]:
    members = await org_service.list_members(db, org_id=org_id)
    return [_to_response(m) for m in members]


@router.patch(
    "/{user_id}",
    response_model=MembershipResponse,
    summary="Change member role",
    description="Update a member's role. Requires roles.manage. Audited as role.changed.",
)
async def change_role(
    org_id: UUID,
    user_id: UUID,
    body: MembershipRoleUpdate,
    membership: Annotated[OrgMembership, Depends(require_permission("roles.manage"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MembershipResponse:
    updated = await org_service.update_member_role(
        db,
        org_id=org_id,
        member_user_id=user_id,
        role_name=body.role_name,
        actor_id=membership.user_id,
    )
    return _to_response(updated)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove member",
    description="Remove a member from the organization. Requires users.remove.",
)
async def remove_member(
    org_id: UUID,
    user_id: UUID,
    membership: Annotated[OrgMembership, Depends(require_permission("users.remove"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await org_service.remove_member(
        db,
        org_id=org_id,
        member_user_id=user_id,
        actor_id=membership.user_id,
    )
