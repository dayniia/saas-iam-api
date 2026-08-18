from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.deps import get_current_user
from app.core.rate_limit import rate_limit
from app.database import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Auth"])
settings = get_settings()


@router.post(
    "/signup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Create an account with email and password. Does not return tokens — call /login next.",
)
async def signup(
    body: SignupRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    return await auth_service.signup(
        db,
        email=body.email,
        password=body.password,
        full_name=body.full_name,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in",
    description="Authenticate with email/password. Returns a short-lived access JWT and a refresh token.",
    dependencies=[Depends(rate_limit(settings.rate_limit_login, key_prefix="login"))],
)
async def login(
    body: LoginRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    ua = request.headers.get("user-agent")
    ip = request.client.host if request.client else None
    _user, access, refresh = await auth_service.login(
        db,
        email=body.email,
        password=body.password,
        user_agent=ua,
        ip_address=ip,
    )
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Rotate refresh token",
    description=(
        "Exchange a valid refresh token for a new access + refresh pair. "
        "Reuse of an already-rotated refresh token revokes the entire session family."
    ),
    dependencies=[Depends(rate_limit(settings.rate_limit_refresh, key_prefix="refresh"))],
)
async def refresh(
    body: RefreshRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    ua = request.headers.get("user-agent")
    ip = request.client.host if request.client else None
    access, refresh_token = await auth_service.refresh_tokens(
        db,
        refresh_token=body.refresh_token,
        user_agent=ua,
        ip_address=ip,
    )
    return TokenResponse(access_token=access, refresh_token=refresh_token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log out",
    description="Revoke the presented refresh token session.",
)
async def logout(
    body: RefreshRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await auth_service.logout(db, refresh_token=body.refresh_token)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Current user",
    description="Return the authenticated user profile from the access token.",
)
async def me(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    return user
