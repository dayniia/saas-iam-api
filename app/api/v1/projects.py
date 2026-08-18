from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_permission
from app.database import get_db
from app.exceptions import NotFoundError
from app.models.membership import OrgMembership
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate
from app.services import project_service

router = APIRouter(prefix="/orgs/{org_id}/projects", tags=["Projects"])


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create project",
    description="Create a project owned by the caller. Requires projects.write.",
)
async def create_project(
    org_id: UUID,
    body: ProjectCreate,
    membership: Annotated[OrgMembership, Depends(require_permission("projects.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectResponse:
    from app.models.user import User

    user = await db.get(User, membership.user_id)
    if user is None:
        raise NotFoundError("User not found")
    project = await project_service.create_project(
        db,
        organization_id=org_id,
        owner=user,
        name=body.name,
        description=body.description,
    )
    return ProjectResponse.model_validate(project)


@router.get(
    "",
    response_model=list[ProjectResponse],
    summary="List projects",
    description="List projects in the organization. Requires projects.read.",
)
async def list_projects(
    org_id: UUID,
    _membership: Annotated[OrgMembership, Depends(require_permission("projects.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ProjectResponse]:
    projects = await project_service.list_projects(db, organization_id=org_id)
    return [ProjectResponse.model_validate(p) for p in projects]


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get project",
    description="Get a project. Cross-tenant access returns 404.",
)
async def get_project(
    org_id: UUID,
    project_id: UUID,
    _membership: Annotated[OrgMembership, Depends(require_permission("projects.read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectResponse:
    project = await project_service.get_project_in_org(
        db, organization_id=org_id, project_id=project_id
    )
    return ProjectResponse.model_validate(project)


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Update project",
    description=(
        "Update a project. Requires projects.write plus ownership "
        "(or admin/owner role)."
    ),
)
async def update_project(
    org_id: UUID,
    project_id: UUID,
    body: ProjectUpdate,
    membership: Annotated[OrgMembership, Depends(require_permission("projects.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectResponse:
    project = await project_service.get_project_in_org(
        db, organization_id=org_id, project_id=project_id
    )
    updated = await project_service.update_project(
        db,
        project=project,
        membership=membership,
        name=body.name,
        description=body.description,
    )
    return ProjectResponse.model_validate(updated)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete project",
    description="Delete a project. Owner or admin/owner role required (plus projects.write).",
)
async def delete_project(
    org_id: UUID,
    project_id: UUID,
    membership: Annotated[OrgMembership, Depends(require_permission("projects.write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    project = await project_service.get_project_in_org(
        db, organization_id=org_id, project_id=project_id
    )
    await project_service.delete_project(db, project=project, membership=membership)
