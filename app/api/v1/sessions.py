from typing import Annotated

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.security import hash_token
from app.database import get_db
from app.models.user import User
from app.schemas.auth import RefreshRequest
from app.schemas.session import SessionResponse
from app.services import auth_service
from uuid import UUID

router = APIRouter(prefix="/me/sessions", tags=["Sessions"])


@router.get(
    "",
    response_model=list[SessionResponse],
    summary="List my sessions",
    description=(
        "List refresh-token sessions for the current user. "
        "Pass the current refresh token via the `X-Refresh-Token` header "
        "to have it marked as `is_current=true` in the response."
    ),
)
async def list_sessions(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    x_refresh_token: Annotated[str | None, Header(alias="X-Refresh-Token")] = None,
) -> list[SessionResponse]:
    current_hash = hash_token(x_refresh_token) if x_refresh_token else None
    rows = await auth_service.list_sessions(
        db, user_id=user.id, current_refresh_hash=current_hash
    )
    return [
        SessionResponse(
            id=s.id,
            user_agent=s.user_agent,
            ip_address=s.ip_address,
            expires_at=s.expires_at,
            revoked_at=s.revoked_at,
            created_at=s.created_at,
            is_current=is_current,
        )
        for s, is_current in rows
    ]


@router.post(
    "/{session_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a session",
    description="Revoke a specific session belonging to the current user.",
)
async def revoke_session(
    session_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await auth_service.revoke_session(db, user_id=user.id, session_id=session_id)
