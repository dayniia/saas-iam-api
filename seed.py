"""Seed system roles and permissions.

Idempotent — safe to run multiple times.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models.permission import Permission
from app.models.role import Role

PERMISSIONS: list[tuple[str, str]] = [
    ("users.read", "List and view organization members"),
    ("users.remove", "Remove members from the organization"),
    ("invite", "Create and manage invitations"),
    ("roles.manage", "Change member roles"),
    ("projects.read", "View projects"),
    ("projects.write", "Create and modify projects"),
    ("audit.read", "View audit logs"),
    ("billing.read", "Stub: view billing (deferred)"),
    ("org.manage", "Manage organization settings"),
]

# role name -> permission codenames
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "owner": [
        "users.read",
        "users.remove",
        "invite",
        "roles.manage",
        "projects.read",
        "projects.write",
        "audit.read",
        "billing.read",
        "org.manage",
    ],
    "admin": [
        "users.read",
        "users.remove",
        "invite",
        "roles.manage",
        "projects.read",
        "projects.write",
        "audit.read",
        "billing.read",
    ],
    "member": [
        "users.read",
        "projects.read",
        "projects.write",
    ],
    "viewer": [
        "users.read",
        "projects.read",
    ],
}


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        perm_by_code: dict[str, Permission] = {}
        for codename, description in PERMISSIONS:
            existing = await db.scalar(
                select(Permission).where(Permission.codename == codename)
            )
            if existing:
                perm_by_code[codename] = existing
            else:
                p = Permission(codename=codename, description=description)
                db.add(p)
                await db.flush()
                perm_by_code[codename] = p

        for role_name, codes in ROLE_PERMISSIONS.items():
            role = await db.scalar(
                select(Role)
                .where(
                    Role.name == role_name,
                    Role.is_system.is_(True),
                    Role.organization_id.is_(None),
                )
                .options(selectinload(Role.permissions))
            )
            if role is None:
                role = Role(name=role_name, is_system=True, organization_id=None)
                # Append permissions while role is still pending (no DB lazy-load triggered)
                for code in codes:
                    role.permissions.append(perm_by_code[code])
                db.add(role)
                await db.flush()
            else:
                # Role already exists — permissions eagerly loaded via selectinload
                have = {p.codename for p in role.permissions}
                for code in codes:
                    if code not in have:
                        role.permissions.append(perm_by_code[code])

        await db.commit()
        print("Seeded system roles and permissions.")


if __name__ == "__main__":
    asyncio.run(seed())
