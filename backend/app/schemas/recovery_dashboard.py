from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class CasesSummary(BaseModel):
    total: int = 0
    active: int = 0
    resolved: int = 0


class FinancialSummary(BaseModel):
    total_amount_in_recovery: Decimal = Field(default=Decimal("0.00"))
    total_recovered: Decimal = Field(default=Decimal("0.00"))
    total_outstanding: Decimal = Field(default=Decimal("0.00"))
    total_overdue: Decimal = Field(default=Decimal("0.00"))
    invoices_count: int = 0
    overdue_invoices_count: int = 0


class PromiseSummary(BaseModel):
    total: int = 0
    pending: int = 0
    fulfilled: int = 0
    broken: int = 0


class ActivitySummary(BaseModel):
    actions_count: int = 0
    last_7_days: int = 0


class RecoveryDashboardSummary(BaseModel):
    cases: CasesSummary
    financial: FinancialSummary
    promises: PromiseSummary
    activity: ActivitySummary


class RecoveryActivityItem(BaseModel):
    id: str
    action: str
    entity_type: str
    entity_id: str
    timestamp: datetime
    details: dict | None = None
    user_id: str | None = None

    model_config = {"from_attributes": True}
