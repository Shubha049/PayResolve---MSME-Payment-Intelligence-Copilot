from decimal import Decimal
from pydantic import BaseModel


class DashboardSummary(BaseModel):
    total_invoiced: Decimal
    total_paid: Decimal
    total_outstanding: Decimal
    total_overdue: Decimal
    invoices_count: int
    overdue_invoices_count: int
    active_cases_count: int
    customers_count: int
