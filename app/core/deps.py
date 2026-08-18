from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import NotFoundError, UnauthorizedError, ValidationAppError
from app.models.membership import OrgMembership
from app.models.user import User
from app.services import auth_service, rbac_service

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError("Not authenticated")
    return await auth_service.get_user_by_access_token(db, credentials.credentials)


async def get_org_id_header(
    x_org_id: Annotated[str | None, Header(alias="X-Org-Id")] = None,
) -> uuid.UUID:
    if not x_org_id:
        raise ValidationAppError("X-Org-Id header is required")
    try:
        return uuid.UUID(x_org_id)
    except ValueError as exc:
        raise ValidationAppError("Invalid X-Org-Id header") from exc


async def resolve_org_id(
    org_id: uuid.UUID,
    header_org_id: Annotated[uuid.UUID, Depends(get_org_id_header)],
) -> uuid.UUID:
    """Path org_id must match X-Org-Id — mismatch returns 404 (no tenant leak)."""
    if org_id != header_org_id:
        raise NotFoundError("Organization not found")
    return org_id


def require_permission(permission: str) -> Callable:
    async def _dependency(
        org_id: Annotated[uuid.UUID, Depends(resolve_org_id)],
        user: Annotated[User, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> OrgMembership:
        return await rbac_service.ensure_permission(
            db,
            user_id=user.id,
            organization_id=org_id,
            permission=permission,
        )

    return _dependency


async def get_current_membership(
    org_id: Annotated[uuid.UUID, Depends(resolve_org_id)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrgMembership:
    return await rbac_service.require_membership(
        db, user_id=user.id, organization_id=org_id
    )
