from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import ForbiddenError, NotFoundError
from app.models.membership import OrgMembership
from app.models.permission import Permission
from app.models.role import Role


async def get_system_role(db: AsyncSession, name: str) -> Role:
    role = await db.scalar(
        select(Role).where(Role.name == name, Role.is_system.is_(True), Role.organization_id.is_(None))
    )
    if role is None:
        raise NotFoundError(f"System role '{name}' not found — run seed.py")
    return role


async def get_membership(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> OrgMembership | None:
    return await db.scalar(
        select(OrgMembership)
        .where(
            OrgMembership.user_id == user_id,
            OrgMembership.organization_id == organization_id,
        )
        .options(selectinload(OrgMembership.role).selectinload(Role.permissions))
    )


async def has_permission(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    permission: str,
) -> bool:
    membership = await get_membership(
        db, user_id=user_id, organization_id=organization_id
    )
    if membership is None or membership.role is None:
        return False
    return any(p.codename == permission for p in membership.role.permissions)


async def require_membership(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> OrgMembership:
    membership = await get_membership(
        db, user_id=user_id, organization_id=organization_id
    )
    if membership is None:
        # Cross-tenant: never confirm org exists
        raise NotFoundError("Organization not found")
    return membership


async def ensure_permission(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    permission: str,
) -> OrgMembership:
    membership = await require_membership(
        db, user_id=user_id, organization_id=organization_id
    )
    perms = {p.codename for p in membership.role.permissions}
    if permission not in perms:
        raise ForbiddenError(f"Missing permission: {permission}")
    return membership
