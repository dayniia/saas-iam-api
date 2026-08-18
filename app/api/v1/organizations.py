from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.schemas.organization import OrganizationCreate, OrganizationResponse
from app.services import org_service

router = APIRouter(prefix="/orgs", tags=["Organizations"])


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create organization",
    description="Create a workspace and assign the caller the owner role.",
)
async def create_org(
    body: OrganizationCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Organization:
    return await org_service.create_organization(
        db, user=user, name=body.name, slug=body.slug
    )


@router.get(
    "",
    response_model=list[OrganizationResponse],
    summary="List my organizations",
    description="List organizations the authenticated user belongs to.",
)
async def list_orgs(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Organization]:
    return await org_service.list_user_organizations(db, user_id=user.id)


@router.get(
    "/{org_id}",
    response_model=OrganizationResponse,
    summary="Get organization",
    description="Get an organization by id. Returns 404 if the caller is not a member.",
)
async def get_org(
    org_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Organization:
    return await org_service.get_organization(db, org_id=org_id, user_id=user.id)
