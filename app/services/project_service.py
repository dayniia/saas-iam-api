from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ForbiddenError, NotFoundError
from app.models.membership import OrgMembership
from app.models.project import Project
from app.models.user import User
from app.services.audit_service import write_audit_log


async def create_project(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    owner: User,
    name: str,
    description: str | None,
) -> Project:
    project = Project(
        organization_id=organization_id,
        owner_id=owner.id,
        name=name,
        description=description,
    )
    db.add(project)
    await db.flush()
    await write_audit_log(
        db,
        action="project.created",
        actor_id=owner.id,
        organization_id=organization_id,
        resource_type="project",
        resource_id=project.id,
        metadata={"name": name},
    )
    return project


async def get_project_in_org(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
) -> Project:
    project = await db.get(Project, project_id)
    if project is None or project.organization_id != organization_id:
        raise NotFoundError("Project not found")
    return project


async def list_projects(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> list[Project]:
    result = await db.scalars(
        select(Project)
        .where(Project.organization_id == organization_id)
        .order_by(Project.created_at.desc())
    )
    return list(result.all())


async def update_project(
    db: AsyncSession,
    *,
    project: Project,
    membership: OrgMembership,
    name: str | None,
    description: str | None,
) -> Project:
    role_name = membership.role.name if membership.role else ""
    is_privileged = role_name in ("owner", "admin")
    is_owner = project.owner_id == membership.user_id
    if not (is_privileged or is_owner):
        raise ForbiddenError("Only the project owner or an admin can update this project")

    if name is not None:
        project.name = name
    if description is not None:
        project.description = description

    await write_audit_log(
        db,
        action="project.updated",
        actor_id=membership.user_id,
        organization_id=project.organization_id,
        resource_type="project",
        resource_id=project.id,
        metadata={"name": project.name},
    )
    await db.flush()
    return project


async def delete_project(
    db: AsyncSession,
    *,
    project: Project,
    membership: OrgMembership,
) -> None:
    role_name = membership.role.name if membership.role else ""
    is_privileged = role_name in ("owner", "admin")
    is_owner = project.owner_id == membership.user_id
    if not (is_privileged or is_owner):
        raise ForbiddenError("Only the project owner or an admin can delete this project")

    await write_audit_log(
        db,
        action="project.deleted",
        actor_id=membership.user_id,
        organization_id=project.organization_id,
        resource_type="project",
        resource_id=project.id,
        metadata={},
    )
    await db.delete(project)
