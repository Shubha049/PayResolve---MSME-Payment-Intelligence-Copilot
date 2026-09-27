"""Payment schemas for API serialization and validation."""
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field
from typing import Optional


class PaymentBase(BaseModel):
    """Base payment schema with common fields."""
    invoice_id: str = Field(..., description="Invoice ID (UUID) this payment is for")
    amount: Decimal = Field(..., gt=0, description="Payment amount (must be positive)")
    payment_date: date = Field(..., description="Date payment was received")
    reference: Optional[str] = Field(None, max_length=255, description="Payment reference (e.g., check number, transaction ID)")


class PaymentCreate(PaymentBase):
    """Schema for creating a new payment."""
    pass


class PaymentRead(PaymentBase):
    """Schema for reading payment data."""
    id: str
    organization_id: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PaymentListResponse(BaseModel):
    """Response schema for listing payments."""
    payments: list[PaymentRead]
    total: int
