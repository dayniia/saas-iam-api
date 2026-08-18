from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class InvitationCreate(BaseModel):
    email: EmailStr
    role_name: str = Field(pattern=r"^(admin|member|viewer)$")


class InvitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    email: EmailStr
    role_id: UUID
    invited_by: UUID
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime
    # Returned only at create time (not emailed in MVP)
    invite_token: str | None = None


class InvitationAccept(BaseModel):
    token: str
