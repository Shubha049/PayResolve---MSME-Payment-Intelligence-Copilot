from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, ConfigDict


class CustomerBase(BaseModel):
    name: str
    tax_id: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = None


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    tax_id: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = None


class CustomerRead(CustomerBase):
    id: str
    organization_id: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
