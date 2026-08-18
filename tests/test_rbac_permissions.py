import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers, signup_and_login


async def _create_org(client: AsyncClient, access: str, slug: str) -> dict:
    r = await client.post(
        "/api/v1/orgs",
        headers=auth_headers(access),
        json={"name": slug.title(), "slug": slug},
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_cross_tenant_project_returns_404(client: AsyncClient) -> None:
    """Org A must not read Org B's projects — 404, not 403."""
    a = await signup_and_login(client, email="owner-a@example.com")
    b = await signup_and_login(client, email="owner-b@example.com")

    org_a = await _create_org(client, a["access_token"], "org-alpha")
    org_b = await _create_org(client, b["access_token"], "org-beta")

    # Create project in org B
    r = await client.post(
        f"/api/v1/orgs/{org_b['id']}/projects",
        headers=auth_headers(b["access_token"], org_b["id"]),
        json={"name": "Secret Project", "description": "private"},
    )
    assert r.status_code == 201, r.text
    project = r.json()

    # Owner A tries to read it with Org A header + Org B path → 404 (header mismatch)
    r404 = await client.get(
        f"/api/v1/orgs/{org_b['id']}/projects/{project['id']}",
        headers=auth_headers(a["access_token"], org_a["id"]),
    )
    assert r404.status_code == 404

    # Owner A tries with Org B path and forged Org B header (not a member) → 404
    r404b = await client.get(
        f"/api/v1/orgs/{org_b['id']}/projects/{project['id']}",
        headers=auth_headers(a["access_token"], org_b["id"]),
    )
    assert r404b.status_code == 404


@pytest.mark.asyncio
async def test_viewer_cannot_write_project(client: AsyncClient) -> None:
    owner = await signup_and_login(client, email="owner-rbac@example.com")
    viewer = await signup_and_login(client, email="viewer-rbac@example.com")
    org = await _create_org(client, owner["access_token"], "rbac-org")

    # Invite viewer
    inv = await client.post(
        f"/api/v1/orgs/{org['id']}/invites",
        headers=auth_headers(owner["access_token"], org["id"]),
        json={"email": "viewer-rbac@example.com", "role_name": "viewer"},
    )
    assert inv.status_code == 201, inv.text
    token = inv.json()["invite_token"]

    acc = await client.post(
        "/api/v1/invites/accept",
        headers=auth_headers(viewer["access_token"]),
        json={"token": token},
    )
    assert acc.status_code == 200, acc.text

    # Viewer can read
    r = await client.get(
        f"/api/v1/orgs/{org['id']}/projects",
        headers=auth_headers(viewer["access_token"], org["id"]),
    )
    assert r.status_code == 200

    # Viewer cannot write
    r2 = await client.post(
        f"/api/v1/orgs/{org['id']}/projects",
        headers=auth_headers(viewer["access_token"], org["id"]),
        json={"name": "Nope"},
    )
    assert r2.status_code == 403


@pytest.mark.asyncio
async def test_non_owner_member_cannot_edit_others_project(client: AsyncClient) -> None:
    owner = await signup_and_login(client, email="proj-owner@example.com")
    member = await signup_and_login(client, email="proj-member@example.com")
    org = await _create_org(client, owner["access_token"], "proj-org")

    inv = await client.post(
        f"/api/v1/orgs/{org['id']}/invites",
        headers=auth_headers(owner["access_token"], org["id"]),
        json={"email": "proj-member@example.com", "role_name": "member"},
    )
    token = inv.json()["invite_token"]
    await client.post(
        "/api/v1/invites/accept",
        headers=auth_headers(member["access_token"]),
        json={"token": token},
    )

    created = await client.post(
        f"/api/v1/orgs/{org['id']}/projects",
        headers=auth_headers(owner["access_token"], org["id"]),
        json={"name": "Owner Project"},
    )
    project = created.json()

    # Member has projects.write but is not owner → 403 on update
    r = await client.patch(
        f"/api/v1/orgs/{org['id']}/projects/{project['id']}",
        headers=auth_headers(member["access_token"], org["id"]),
        json={"name": "Hijacked"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_member_cannot_change_role(client: AsyncClient) -> None:
    """A member (lacks roles.manage) must get 403 trying to change another member's role."""
    owner = await signup_and_login(client, email="role-owner@example.com")
    member = await signup_and_login(client, email="role-member@example.com")
    target = await signup_and_login(client, email="role-target@example.com")
    org = await _create_org(client, owner["access_token"], "role-change-org")

    # Invite member
    inv = await client.post(
        f"/api/v1/orgs/{org['id']}/invites",
        headers=auth_headers(owner["access_token"], org["id"]),
        json={"email": "role-member@example.com", "role_name": "member"},
    )
    assert inv.status_code == 201
    await client.post(
        "/api/v1/invites/accept",
        headers=auth_headers(member["access_token"]),
        json={"token": inv.json()["invite_token"]},
    )

    # Invite target
    inv2 = await client.post(
        f"/api/v1/orgs/{org['id']}/invites",
        headers=auth_headers(owner["access_token"], org["id"]),
        json={"email": "role-target@example.com", "role_name": "viewer"},
    )
    assert inv2.status_code == 201
    target_inv_resp = await client.post(
        "/api/v1/invites/accept",
        headers=auth_headers(target["access_token"]),
        json={"token": inv2.json()["invite_token"]},
    )
    target_user_id = target_inv_resp.json()["user_id"]

    # Member attempts to change target's role — must be 403 (lacks roles.manage)
    r = await client.patch(
        f"/api/v1/orgs/{org['id']}/members/{target_user_id}",
        headers=auth_headers(member["access_token"], org["id"]),
        json={"role_name": "admin"},
    )
    assert r.status_code == 403
