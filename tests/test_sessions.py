import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers, signup_and_login


@pytest.mark.asyncio
async def test_list_and_revoke_session(client: AsyncClient) -> None:
    data = await signup_and_login(client, email="sess@example.com")

    r = await client.get(
        "/api/v1/me/sessions",
        headers=auth_headers(data["access_token"]) | {"X-Refresh-Token": data["refresh_token"]},
    )
    assert r.status_code == 200
    sessions = r.json()
    assert len(sessions) >= 1
    active = [s for s in sessions if s["revoked_at"] is None]
    assert active

    session_id = active[0]["id"]
    rev = await client.post(
        f"/api/v1/me/sessions/{session_id}/revoke",
        headers=auth_headers(data["access_token"]),
    )
    assert rev.status_code == 204

    # Refresh should fail
    bad = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": data["refresh_token"]},
    )
    assert bad.status_code == 401


@pytest.mark.asyncio
async def test_cannot_revoke_another_users_session(client: AsyncClient) -> None:
    """User B must not be able to revoke User A's session — expects 404."""
    user_a = await signup_and_login(client, email="sess-a@example.com")
    user_b = await signup_and_login(client, email="sess-b@example.com")

    # Get user A's active session id
    r = await client.get(
        "/api/v1/me/sessions",
        headers=auth_headers(user_a["access_token"]) | {"X-Refresh-Token": user_a["refresh_token"]},
    )
    assert r.status_code == 200
    session_id = next(s["id"] for s in r.json() if s["revoked_at"] is None)

    # User B attempts to revoke User A's session
    bad = await client.post(
        f"/api/v1/me/sessions/{session_id}/revoke",
        headers=auth_headers(user_b["access_token"]),
    )
    assert bad.status_code == 404
