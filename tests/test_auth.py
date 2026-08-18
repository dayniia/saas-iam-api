from datetime import timedelta

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from tests.conftest import signup_and_login


@pytest.mark.asyncio
async def test_signup_login_me(client: AsyncClient) -> None:
    data = await signup_and_login(client, email="alice@example.com")
    r = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert r.status_code == 200
    assert r.json()["email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient) -> None:
    await signup_and_login(client, email="bob@example.com")
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": "wrong-password"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rotation(client: AsyncClient) -> None:
    data = await signup_and_login(client, email="carol@example.com")
    old_refresh = data["refresh_token"]
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 200
    new_tokens = r.json()
    assert new_tokens["refresh_token"] != old_refresh

    # New refresh works
    r2 = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": new_tokens["refresh_token"]},
    )
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_refresh_reuse_revokes_family(client: AsyncClient) -> None:
    data = await signup_and_login(client, email="dave@example.com")
    old_refresh = data["refresh_token"]

    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 200
    rotated = r.json()

    # Replay the already-rotated token
    reuse = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": old_refresh}
    )
    assert reuse.status_code == 401
    assert "reuse" in reuse.json()["detail"].lower()

    # The rotated child should also be dead (family revoked)
    child = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": rotated["refresh_token"]},
    )
    assert child.status_code == 401


@pytest.mark.asyncio
async def test_logout(client: AsyncClient) -> None:
    data = await signup_and_login(client, email="eve@example.com")
    r = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": data["refresh_token"]},
    )
    assert r.status_code == 204
    r2 = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": data["refresh_token"]},
    )
    assert r2.status_code == 401


@pytest.mark.asyncio
async def test_duplicate_signup(client: AsyncClient) -> None:
    await signup_and_login(client, email="frank@example.com")
    r = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": "frank@example.com",
            "password": "password123",
            "full_name": "Frank",
        },
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_expired_access_token_returns_401(client: AsyncClient) -> None:
    """An already-expired access JWT must be rejected by /me with 401."""
    data = await signup_and_login(client, email="grace@example.com")
    # Pull the user UUID from the valid response so we can forge an expired token
    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert me.status_code == 200
    import uuid
    user_id = uuid.UUID(me.json()["id"])

    expired_token = create_access_token(user_id, expires_delta=timedelta(seconds=-1))
    r = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert r.status_code == 401
