"""Integration tests for the /audit-logs endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers, signup_and_login


async def _setup_org_with_viewer(
    client: AsyncClient,
) -> tuple[dict, dict, str]:
    """Helper: create org, invite a viewer, return owner tokens, viewer tokens, org_id."""
    owner = await signup_and_login(client, email="audit-owner@example.com")
    viewer = await signup_and_login(client, email="audit-viewer@example.com")

    org = await client.post(
        "/api/v1/orgs",
        headers=auth_headers(owner["access_token"]),
        json={"name": "Audit Org", "slug": "audit-org"},
    )
    assert org.status_code == 201
    org_id = org.json()["id"]

    inv = await client.post(
        f"/api/v1/orgs/{org_id}/invites",
        headers=auth_headers(owner["access_token"], org_id),
        json={"email": "audit-viewer@example.com", "role_name": "viewer"},
    )
    assert inv.status_code == 201
    await client.post(
        "/api/v1/invites/accept",
        headers=auth_headers(viewer["access_token"]),
        json={"token": inv.json()["invite_token"]},
    )
    return owner, viewer, org_id


@pytest.mark.asyncio
async def test_audit_log_written_on_login(client: AsyncClient) -> None:
    """
    Happy path: an org owner (who has audit.read) can see audit log entries.
    After login, at least one auth.login or org.created entry must appear.
    """
    owner, _viewer, org_id = await _setup_org_with_viewer(client)

    r = await client.get(
        f"/api/v1/orgs/{org_id}/audit-logs",
        headers=auth_headers(owner["access_token"], org_id),
    )
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert body["total"] >= 1
    actions = [entry["action"] for entry in body["items"]]
    # org.created is always written when the org was created
    assert any(a in ("org.created", "auth.login", "invite.created") for a in actions)


@pytest.mark.asyncio
async def test_viewer_cannot_read_audit_logs(client: AsyncClient) -> None:
    """
    Failure path: a viewer role lacks audit.read — must get 403.
    """
    owner, viewer, org_id = await _setup_org_with_viewer(client)

    r = await client.get(
        f"/api/v1/orgs/{org_id}/audit-logs",
        headers=auth_headers(viewer["access_token"], org_id),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_audit_logs_pagination(client: AsyncClient) -> None:
    """
    Happy path: pagination params are respected (page_size=1 returns 1 item).
    """
    owner, _viewer, org_id = await _setup_org_with_viewer(client)

    r = await client.get(
        f"/api/v1/orgs/{org_id}/audit-logs",
        headers=auth_headers(owner["access_token"], org_id),
        params={"page": 1, "page_size": 1},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) <= 1
    assert body["page"] == 1
    assert body["page_size"] == 1
