from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models.membership import OrgMembership
from app.models.organization import Organization
from app.models.role import Role
from app.models.user import User
from app.services.audit_service import write_audit_log
from app.services.rbac_service import get_system_role


async def create_organization(
    db: AsyncSession,
    *,
    user: User,
    name: str,
    slug: str,
) -> Organization:
    existing = await db.scalar(select(Organization).where(Organization.slug == slug))
    if existing:
        raise ConflictError("Organization slug already taken")

    org = Organization(name=name, slug=slug, created_by=user.id)
    db.add(org)
    await db.flush()

    owner_role = await get_system_role(db, "owner")
    membership = OrgMembership(
        organization_id=org.id,
        user_id=user.id,
        role_id=owner_role.id,
    )
    db.add(membership)
    await write_audit_log(
        db,
        action="org.created",
        actor_id=user.id,
        organization_id=org.id,
        resource_type="organization",
        resource_id=org.id,
        metadata={"name": name, "slug": slug},
    )
    await db.flush()
    return org


async def get_organization(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Organization:
    membership = await db.scalar(
        select(OrgMembership).where(
            OrgMembership.organization_id == org_id,
            OrgMembership.user_id == user_id,
        )
    )
    if membership is None:
        raise NotFoundError("Organization not found")

    org = await db.get(Organization, org_id)
    if org is None:
        raise NotFoundError("Organization not found")
    return org


async def list_user_organizations(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> list[Organization]:
    result = await db.scalars(
        select(Organization)
        .join(OrgMembership, OrgMembership.organization_id == Organization.id)
        .where(OrgMembership.user_id == user_id)
        .order_by(Organization.created_at.desc())
    )
    return list(result.all())


async def list_members(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> list[OrgMembership]:
    result = await db.scalars(
        select(OrgMembership)
        .where(OrgMembership.organization_id == org_id)
        .options(selectinload(OrgMembership.user), selectinload(OrgMembership.role))
        .order_by(OrgMembership.created_at.asc())
    )
    return list(result.all())


async def update_member_role(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    member_user_id: uuid.UUID,
    role_name: str,
    actor_id: uuid.UUID,
) -> OrgMembership:
    membership = await db.scalar(
        select(OrgMembership)
        .where(
            OrgMembership.organization_id == org_id,
            OrgMembership.user_id == member_user_id,
        )
        .options(selectinload(OrgMembership.role), selectinload(OrgMembership.user))
    )
    if membership is None:
        raise NotFoundError("Member not found")

    new_role = await get_system_role(db, role_name)
    old_role_name = membership.role.name if membership.role else None

    if old_role_name == "owner" and role_name != "owner":
        # Prevent removing the last owner
        owners = await db.scalars(
            select(OrgMembership)
            .join(Role, Role.id == OrgMembership.role_id)
            .where(
                OrgMembership.organization_id == org_id,
                Role.name == "owner",
            )
        )
        if len(list(owners.all())) <= 1:
            raise ValidationAppError("Cannot demote the last owner")

    membership.role_id = new_role.id
    await write_audit_log(
        db,
        action="role.changed",
        actor_id=actor_id,
        organization_id=org_id,
        resource_type="membership",
        resource_id=membership.id,
        metadata={
            "user_id": str(member_user_id),
            "old_role": old_role_name,
            "new_role": role_name,
        },
    )
    await db.flush()
    await db.refresh(membership, attribute_names=["role", "user"])
    return membership


async def remove_member(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    member_user_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> None:
    membership = await db.scalar(
        select(OrgMembership)
        .where(
            OrgMembership.organization_id == org_id,
            OrgMembership.user_id == member_user_id,
        )
        .options(selectinload(OrgMembership.role))
    )
    if membership is None:
        raise NotFoundError("Member not found")

    if membership.role and membership.role.name == "owner":
        owners = await db.scalars(
            select(OrgMembership)
            .join(Role, Role.id == OrgMembership.role_id)
            .where(
                OrgMembership.organization_id == org_id,
                Role.name == "owner",
            )
        )
        if len(list(owners.all())) <= 1:
            raise ValidationAppError("Cannot remove the last owner")

    await db.delete(membership)
    await write_audit_log(
        db,
        action="member.removed",
        actor_id=actor_id,
        organization_id=org_id,
        resource_type="user",
        resource_id=member_user_id,
        metadata={},
    )
