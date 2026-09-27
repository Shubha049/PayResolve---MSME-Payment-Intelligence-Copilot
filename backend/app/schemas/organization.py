from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict
from app.models.organization import MemberRole


class OrganizationBase(BaseModel):
    name: str


class OrganizationCreate(OrganizationBase):
    slug: Optional[str] = None


class OrganizationRead(OrganizationBase):
    id: str
    slug: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class MemberRead(BaseModel):
    id: str
    user_id: str
    email: str
    full_name: str
    role: MemberRole
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class MemberInvite(BaseModel):
    email: str
    role: MemberRole = MemberRole.MEMBER
