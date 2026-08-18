from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.deps import get_current_user, require_permission
from app.core.rate_limit import rate_limit
from app.database import get_db
from app.models.invitation import Invitation
from app.models.membership import OrgMembership
from app.models.user import User
from app.schemas.invitation import InvitationAccept, InvitationCreate, InvitationResponse
from app.schemas.membership import MembershipResponse
from app.services import invitation_service

router = APIRouter(tags=["Invitations"])
settings = get_settings()


@router.post(
    "/orgs/{org_id}/invites",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite teammate",
    description=(
        "Create an expiring invite. MVP returns invite_token in the response "
        "(no email delivery). Requires invite permission."
    ),
    dependencies=[Depends(rate_limit(settings.rate_limit_invite, key_prefix="invite"))],
)
async def create_invite(
    org_id: UUID,
    body: InvitationCreate,
    membership: Annotated[OrgMembership, Depends(require_permission("invite"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InvitationResponse:
    invite, token = await invitation_service.create_invitation(
        db,
        organization_id=org_id,
        email=body.email,
        role_name=body.role_name,
        invited_by=membership.user_id,
    )
    return InvitationResponse(
        id=invite.id,
        organization_id=invite.organization_id,
        email=invite.email,
        role_id=invite.role_id,
        invited_by=invite.invited_by,
        expires_at=invite.expires_at,
        accepted_at=invite.accepted_at,
        created_at=invite.created_at,
        invite_token=token,
    )


@router.get(
    "/orgs/{org_id}/invites",
    response_model=list[InvitationResponse],
    summary="List invitations",
    description="List invitations for an organization. Requires invite permission.",
)
async def list_invites(
    org_id: UUID,
    _membership: Annotated[OrgMembership, Depends(require_permission("invite"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[InvitationResponse]:
    invites = await invitation_service.list_invitations(db, organization_id=org_id)
    return [
        InvitationResponse(
            id=i.id,
            organization_id=i.organization_id,
            email=i.email,
            role_id=i.role_id,
            invited_by=i.invited_by,
            expires_at=i.expires_at,
            accepted_at=i.accepted_at,
            created_at=i.created_at,
            invite_token=None,
        )
        for i in invites
    ]


@router.post(
    "/invites/accept",
    response_model=MembershipResponse,
    summary="Accept invitation",
    description="Accept an invite using the raw token. Caller email must match the invite.",
)
async def accept_invite(
    body: InvitationAccept,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MembershipResponse:
    membership = await invitation_service.accept_invitation(
        db, token=body.token, user=user
    )
    return MembershipResponse(
        id=membership.id,
        organization_id=membership.organization_id,
        user_id=membership.user_id,
        role_id=membership.role_id,
        created_at=membership.created_at,
    )
