import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers, signup_and_login


@pytest.mark.asyncio
async def test_invite_and_accept(client: AsyncClient) -> None:
    owner = await signup_and_login(client, email="inv-owner@example.com")
    invitee = await signup_and_login(client, email="inv-user@example.com")

    org = await client.post(
        "/api/v1/orgs",
        headers=auth_headers(owner["access_token"]),
        json={"name": "Invite Co", "slug": "invite-co"},
    )
    assert org.status_code == 201
    org_id = org.json()["id"]

    inv = await client.post(
        f"/api/v1/orgs/{org_id}/invites",
        headers=auth_headers(owner["access_token"], org_id),
        json={"email": "inv-user@example.com", "role_name": "member"},
    )
    assert inv.status_code == 201
    token = inv.json()["invite_token"]
    assert token

    acc = await client.post(
        "/api/v1/invites/accept",
        headers=auth_headers(invitee["access_token"]),
        json={"token": token},
    )
    assert acc.status_code == 200
    assert acc.json()["organization_id"] == org_id


@pytest.mark.asyncio
async def test_invite_email_mismatch(client: AsyncClient) -> None:
    owner = await signup_and_login(client, email="inv2-owner@example.com")
    other = await signup_and_login(client, email="inv2-other@example.com")

    org = await client.post(
        "/api/v1/orgs",
        headers=auth_headers(owner["access_token"]),
        json={"name": "Invite Co 2", "slug": "invite-co-2"},
    )
    org_id = org.json()["id"]

    inv = await client.post(
        f"/api/v1/orgs/{org_id}/invites",
        headers=auth_headers(owner["access_token"], org_id),
        json={"email": "someone-else@example.com", "role_name": "viewer"},
    )
    token = inv.json()["invite_token"]

    acc = await client.post(
        "/api/v1/invites/accept",
        headers=auth_headers(other["access_token"]),
        json={"token": token},
    )
    assert acc.status_code == 422


@pytest.mark.asyncio
async def test_expired_invite_is_rejected(client: AsyncClient, db) -> None:
    """An invitation whose expires_at is in the past must be rejected with 422."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.models.invitation import Invitation

    owner = await signup_and_login(client, email="exp-owner@example.com")
    invitee = await signup_and_login(client, email="exp-invitee@example.com")

    org = await client.post(
        "/api/v1/orgs",
        headers=auth_headers(owner["access_token"]),
        json={"name": "Expiry Co", "slug": "expiry-co"},
    )
    assert org.status_code == 201
    org_id = org.json()["id"]

    inv = await client.post(
        f"/api/v1/orgs/{org_id}/invites",
        headers=auth_headers(owner["access_token"], org_id),
        json={"email": "exp-invitee@example.com", "role_name": "member"},
    )
    assert inv.status_code == 201
    token = inv.json()["invite_token"]

    # Force the invitation to be expired by backdating expires_at
    invite = await db.scalar(
        select(Invitation).where(Invitation.organization_id == org.json()["id"])
    )
    assert invite is not None
    invite.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db.commit()

    acc = await client.post(
        "/api/v1/invites/accept",
        headers=auth_headers(invitee["access_token"]),
        json={"token": token},
    )
    assert acc.status_code == 422
