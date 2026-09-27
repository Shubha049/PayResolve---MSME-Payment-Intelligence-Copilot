from datetime import datetime, date
from typing import Optional
from decimal import Decimal
from pydantic import BaseModel, ConfigDict
from app.models.case import CaseStatus, CasePriority
from app.schemas.customer import CustomerRead
from app.schemas.invoice import InvoiceRead
from app.schemas.user import UserRead


class CaseBase(BaseModel):
    customer_id: str
    invoice_id: Optional[str] = None
    title: str
    case_number: str
    status: CaseStatus = CaseStatus.OPEN
    priority: CasePriority = CasePriority.MEDIUM
    assigned_to_user_id: Optional[str] = None
    summary: Optional[str] = None


class CaseCreate(CaseBase):
    pass


class CaseUpdate(BaseModel):
    customer_id: Optional[str] = None
    invoice_id: Optional[str] = None
    title: Optional[str] = None
    status: Optional[CaseStatus] = None
    priority: Optional[CasePriority] = None
    assigned_to_user_id: Optional[str] = None
    summary: Optional[str] = None


class CaseRead(CaseBase):
    id: str
    organization_id: str
    customer: Optional[CustomerRead] = None
    invoice: Optional[InvoiceRead] = None
    assigned_to: Optional[UserRead] = None
    
    # Recovery workflow fields (Phase 1)
    amount_in_recovery: Optional[Decimal] = None
    expected_payment_date: Optional[date] = None
    last_contact_date: Optional[date] = None
    next_follow_up_date: Optional[date] = None
    
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
