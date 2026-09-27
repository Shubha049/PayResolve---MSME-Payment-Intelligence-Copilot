from pydantic import BaseModel, EmailStr, Field
from typing import Optional


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=128)
    full_name: str = Field(..., min_length=1, max_length=200)
    organization_name: str = Field(..., min_length=1, max_length=200)


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=128)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    organization_id: str
    email: str
    full_name: str


class TokenPayload(BaseModel):
    sub: Optional[str] = None
    exp: Optional[int] = None
