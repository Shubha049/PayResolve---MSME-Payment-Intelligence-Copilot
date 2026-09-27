"""Promise-to-Pay schemas for API serialization and validation."""
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator
from typing import Optional

from app.models.promise import PromiseStatus


class PromiseBase(BaseModel):
    """Base promise schema with common fields."""
    promise_date: date = Field(..., description="Date when customer promises to pay")
    promised_amount: Decimal = Field(..., gt=0, description="Amount customer promises to pay (must be positive)")
    notes: Optional[str] = Field(None, max_length=5000, description="Free-form notes about the promise")


class PromiseCreate(PromiseBase):
    """Schema for creating a new promise."""
    
    @field_validator('promise_date')
    @classmethod
    def validate_promise_date(cls, v: date) -> date:
        """Validate promise date is not in the past."""
        if v < date.today():
            raise ValueError("Promise date cannot be in the past")
        return v


class PromiseUpdate(BaseModel):
    """Schema for updating an existing promise."""
    promise_date: Optional[date] = Field(None, description="Update promise date")
    promised_amount: Optional[Decimal] = Field(None, gt=0, description="Update promised amount")
    status: Optional[PromiseStatus] = Field(None, description="Update promise status")
    notes: Optional[str] = Field(None, max_length=5000, description="Update notes")
    
    @field_validator('promise_date')
    @classmethod
    def validate_promise_date(cls, v: Optional[date]) -> Optional[date]:
        """Validate promise date is not in the past if provided."""
        if v is not None and v < date.today():
            raise ValueError("Promise date cannot be in the past")
        return v


class PromiseRead(PromiseBase):
    """Schema for reading promise data."""
    id: str
    case_id: str
    organization_id: str
    status: PromiseStatus
    fulfilled_by_payment_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PromiseListResponse(BaseModel):
    """Response schema for listing promises."""
    promises: list[PromiseRead]
    total: int
