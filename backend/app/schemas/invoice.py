from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from app.models.invoice import InvoiceStatus
from app.schemas.customer import CustomerRead


class InvoiceBase(BaseModel):
    customer_id: str
    invoice_number: str
    issue_date: date
    due_date: date
    currency: str = "INR"
    total_amount: Decimal = Field(..., gt=0)
    paid_amount: Decimal = Field(default=Decimal("0.00"), ge=0)
    status: InvoiceStatus = InvoiceStatus.ISSUED
    notes: Optional[str] = None


class InvoiceCreate(InvoiceBase):
    pass


class InvoiceUpdate(BaseModel):
    customer_id: Optional[str] = None
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    currency: Optional[str] = None
    total_amount: Optional[Decimal] = Field(None, gt=0)
    paid_amount: Optional[Decimal] = Field(None, ge=0)
    status: Optional[InvoiceStatus] = None
    notes: Optional[str] = None


class InvoiceRead(InvoiceBase):
    id: str
    organization_id: str
    outstanding_amount: Decimal
    customer: Optional[CustomerRead] = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
