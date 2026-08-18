from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_token, hash_token, utcnow
from app.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models.invitation import Invitation
from app.models.membership import OrgMembership
from app.models.user import User
from app.services.audit_service import write_audit_log
from app.services.rbac_service import get_system_role


INVITE_TTL_DAYS = 7


async def create_invitation(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    email: str,
    role_name: str,
    invited_by: uuid.UUID,
) -> tuple[Invitation, str]:
    if role_name == "owner":
        raise ValidationAppError("Cannot invite as owner")

    email_l = email.lower()
    existing_member = await db.scalar(
        select(OrgMembership)
        .join(User, User.id == OrgMembership.user_id)
        .where(
            OrgMembership.organization_id == organization_id,
            User.email == email_l,
        )
    )
    if existing_member:
        raise ConflictError("User is already a member of this organization")

    pending = await db.scalar(
        select(Invitation).where(
            Invitation.organization_id == organization_id,
            Invitation.email == email_l,
            Invitation.accepted_at.is_(None),
            Invitation.expires_at > utcnow(),
        )
    )
    if pending:
        raise ConflictError("A pending invitation already exists for this email")

    role = await get_system_role(db, role_name)
    raw_token = generate_token()
    invite = Invitation(
        organization_id=organization_id,
        email=email_l,
        role_id=role.id,
        token_hash=hash_token(raw_token),
        invited_by=invited_by,
        expires_at=utcnow() + timedelta(days=INVITE_TTL_DAYS),
    )
    db.add(invite)
    await db.flush()
    await write_audit_log(
        db,
        action="invite.created",
        actor_id=invited_by,
        organization_id=organization_id,
        resource_type="invitation",
        resource_id=invite.id,
        metadata={"email": email_l, "role": role_name},
    )
    return invite, raw_token


async def accept_invitation(
    db: AsyncSession,
    *,
    token: str,
    user: User,
) -> OrgMembership:
    invite = await db.scalar(
        select(Invitation).where(Invitation.token_hash == hash_token(token))
    )
    if invite is None:
        raise NotFoundError("Invitation not found")
    if invite.accepted_at is not None:
        raise ValidationAppError("Invitation already accepted")
    if invite.expires_at < utcnow():
        raise ValidationAppError("Invitation expired")
    if user.email.lower() != invite.email.lower():
        raise ValidationAppError("Invitation email does not match the authenticated user")

    existing = await db.scalar(
        select(OrgMembership).where(
            OrgMembership.organization_id == invite.organization_id,
            OrgMembership.user_id == user.id,
        )
    )
    if existing:
        raise ConflictError("Already a member of this organization")

    membership = OrgMembership(
        organization_id=invite.organization_id,
        user_id=user.id,
        role_id=invite.role_id,
    )
    db.add(membership)
    invite.accepted_at = utcnow()
    await write_audit_log(
        db,
        action="invite.accepted",
        actor_id=user.id,
        organization_id=invite.organization_id,
        resource_type="invitation",
        resource_id=invite.id,
        metadata={"email": invite.email},
    )
    await db.flush()
    await db.refresh(membership)
    return membership


async def list_invitations(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> list[Invitation]:
    result = await db.scalars(
        select(Invitation)
        .where(Invitation.organization_id == organization_id)
        .order_by(Invitation.created_at.desc())
    )
    return list(result.all())
