from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr
from pydantic import ConfigDict


class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    is_active: bool = True


class UserCreate(UserBase):
    password: str


class UserRead(UserBase):
    id: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
