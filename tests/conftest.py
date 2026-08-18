from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Ensure test settings before app import
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://tac:tac@localhost:5432/tac_test",
)
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-integration-tests")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("DEBUG", "false")

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.models import *  # noqa: F401,F403
from seed import seed

get_settings.cache_clear()
settings = get_settings()

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
TestSession = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def prepare_database() -> AsyncGenerator[None, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await seed()
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    async with TestSession() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with TestSession() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def signup_and_login(
    client: AsyncClient,
    *,
    email: str | None = None,
    password: str = "password123",
    full_name: str = "Test User",
) -> dict:
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    tokens = r.json()
    return {"email": email, "password": password, **tokens}


def auth_headers(access_token: str, org_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {access_token}"}
    if org_id:
        headers["X-Org-Id"] = org_id
    return headers
