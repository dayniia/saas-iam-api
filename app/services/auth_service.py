from __future__ import annotations

import uuid
from datetime import timedelta

import jwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import (
    create_access_token,
    generate_token,
    hash_password,
    hash_token,
    utcnow,
    verify_password,
)
from app.exceptions import ConflictError, UnauthorizedError
from app.models.session import Session
from app.models.user import User
from app.services.audit_service import write_audit_log

settings = get_settings()


async def signup(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str,
) -> User:
    existing = await db.scalar(select(User).where(User.email == email.lower()))
    if existing:
        raise ConflictError("Email already registered")

    user = User(
        email=email.lower(),
        password_hash=hash_password(password),
        full_name=full_name,
    )
    db.add(user)
    await db.flush()
    return user


async def login(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[User, str, str]:
    user = await db.scalar(select(User).where(User.email == email.lower()))
    if user is None or not verify_password(password, user.password_hash):
        raise UnauthorizedError("Invalid email or password")

    access_token, refresh_token = await _create_session_tokens(
        db,
        user=user,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    await write_audit_log(
        db,
        action="auth.login",
        actor_id=user.id,
        organization_id=None,
        resource_type="user",
        resource_id=user.id,
        metadata={"ip_address": ip_address},
    )
    return user, access_token, refresh_token


async def refresh_tokens(
    db: AsyncSession,
    *,
    refresh_token: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[str, str]:
    token_hash = hash_token(refresh_token)
    session = await db.scalar(
        select(Session).where(Session.refresh_token_hash == token_hash)
    )

    if session is None:
        # Possible reuse of an already-rotated token: look up by raw token is impossible
        # after rotation. Client presents unknown hash — treat as invalid.
        raise UnauthorizedError("Invalid refresh token")

    if session.revoked_at is not None:
        # Reuse detection: already-rotated/revoked token presented again.
        await _revoke_family(db, family_id=session.family_id)
        await write_audit_log(
            db,
            action="auth.refresh_reuse_detected",
            actor_id=session.user_id,
            organization_id=None,
            resource_type="session_family",
            resource_id=session.family_id,
            metadata={"session_id": str(session.id)},
        )
        # Persist revocation even though we raise — get_db would otherwise roll back.
        await db.commit()
        raise UnauthorizedError("Refresh token reuse detected; session family revoked")

    if session.expires_at < utcnow():
        session.revoked_at = utcnow()
        raise UnauthorizedError("Refresh token expired")

    # Rotate: revoke current, issue child session in same family
    session.revoked_at = utcnow()
    await db.flush()

    user = await db.get(User, session.user_id)
    if user is None:
        raise UnauthorizedError("Invalid refresh token")

    access_token, new_refresh = await _create_session_tokens(
        db,
        user=user,
        user_agent=user_agent,
        ip_address=ip_address,
        family_id=session.family_id,
        parent_id=session.id,
    )
    return access_token, new_refresh


async def logout(db: AsyncSession, *, refresh_token: str) -> None:
    token_hash = hash_token(refresh_token)
    session = await db.scalar(
        select(Session).where(Session.refresh_token_hash == token_hash)
    )
    if session is None or session.revoked_at is not None:
        return
    session.revoked_at = utcnow()
    await write_audit_log(
        db,
        action="auth.logout",
        actor_id=session.user_id,
        organization_id=None,
        resource_type="session",
        resource_id=session.id,
        metadata={},
    )


async def logout_all_for_user(db: AsyncSession, *, user_id: uuid.UUID) -> None:
    await db.execute(
        update(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


async def get_user_by_access_token(db: AsyncSession, token: str) -> User:
    try:
        from app.core.security import decode_access_token

        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise UnauthorizedError("Could not validate credentials") from exc

    user = await db.get(User, user_id)
    if user is None:
        raise UnauthorizedError("Could not validate credentials")
    return user


async def list_sessions(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    current_refresh_hash: str | None = None,
) -> list[tuple[Session, bool]]:
    result = await db.scalars(
        select(Session)
        .where(Session.user_id == user_id)
        .order_by(Session.created_at.desc())
    )
    sessions = list(result.all())
    out: list[tuple[Session, bool]] = []
    for s in sessions:
        is_current = (
            current_refresh_hash is not None
            and s.refresh_token_hash == current_refresh_hash
            and s.revoked_at is None
        )
        out.append((s, is_current))
    return out


async def revoke_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
) -> None:
    session = await db.get(Session, session_id)
    if session is None or session.user_id != user_id:
        from app.exceptions import NotFoundError

        raise NotFoundError("Session not found")
    if session.revoked_at is None:
        session.revoked_at = utcnow()
        await write_audit_log(
            db,
            action="session.revoked",
            actor_id=user_id,
            organization_id=None,
            resource_type="session",
            resource_id=session.id,
            metadata={"family_id": str(session.family_id)},
        )


async def _create_session_tokens(
    db: AsyncSession,
    *,
    user: User,
    user_agent: str | None,
    ip_address: str | None,
    family_id: uuid.UUID | None = None,
    parent_id: uuid.UUID | None = None,
) -> tuple[str, str]:
    refresh_raw = generate_token()
    session = Session(
        user_id=user.id,
        refresh_token_hash=hash_token(refresh_raw),
        family_id=family_id or uuid.uuid4(),
        parent_id=parent_id,
        user_agent=(user_agent or "")[:512] or None,
        ip_address=ip_address,
        expires_at=utcnow() + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(session)
    await db.flush()
    access = create_access_token(user.id)
    return access, refresh_raw


async def _revoke_family(db: AsyncSession, *, family_id: uuid.UUID) -> None:
    await db.execute(
        update(Session)
        .where(Session.family_id == family_id, Session.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
