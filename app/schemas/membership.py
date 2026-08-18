from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class MembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    user_id: UUID
    role_id: UUID
    role_name: str | None = None
    user_email: EmailStr | None = None
    user_full_name: str | None = None
    created_at: datetime


class MembershipRoleUpdate(BaseModel):
    role_name: str = Field(pattern=r"^(owner|admin|member|viewer)$")
