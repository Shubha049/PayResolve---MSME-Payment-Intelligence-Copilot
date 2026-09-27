from datetime import date, datetime, timedelta
from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import case, select, func

from app.database import get_db
from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.case import Case, CaseStatus
from app.models.customer import Customer
from app.models.promise import PromiseToPay, PromiseStatus
from app.models.stubs import Payment
from app.schemas.dashboard import DashboardSummary
from app.schemas.recovery_dashboard import (
    ActivitySummary,
    CasesSummary,
    FinancialSummary,
    PromiseSummary,
    RecoveryActivityItem,
    RecoveryDashboardSummary,
)
from app.api.deps import get_current_tenant, TenantContext

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
recovery_router = APIRouter(prefix="/recovery", tags=["Recovery"])


def _as_money(value: Decimal | int | float | str | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    decimal_value = Decimal(str(value)).quantize(Decimal("0.01"))
    return decimal_value


@recovery_router.get("/dashboard", response_model=RecoveryDashboardSummary)
async def get_recovery_dashboard(
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    window_start = today - timedelta(days=7)

    cases_total_stmt = select(func.count(Case.id)).where(Case.organization_id == tenant.organization_id)
    cases_total = (await db.execute(cases_total_stmt)).scalar_one()

    active_cases_stmt = select(func.count(Case.id)).where(
        Case.organization_id == tenant.organization_id,
        Case.status.notin_([CaseStatus.RESOLVED, CaseStatus.CLOSED]),
    )
    active_cases = (await db.execute(active_cases_stmt)).scalar_one()

    resolved_cases_stmt = select(func.count(Case.id)).where(
        Case.organization_id == tenant.organization_id,
        Case.status.in_([CaseStatus.RESOLVED, CaseStatus.CLOSED]),
    )
    resolved_cases = (await db.execute(resolved_cases_stmt)).scalar_one()

    total_invoiced_stmt = select(
        func.coalesce(func.sum(Invoice.total_amount), 0).label("total_invoiced"),
        func.coalesce(func.sum(Invoice.paid_amount), 0).label("total_paid"),
        func.count(Invoice.id).label("invoices_count"),
    ).where(Invoice.organization_id == tenant.organization_id)
    total_invoiced_res = (await db.execute(total_invoiced_stmt)).one()

    total_invoiced = _as_money(total_invoiced_res.total_invoiced)
    total_paid = _as_money(total_invoiced_res.total_paid)
    total_outstanding = max(Decimal("0.00"), total_invoiced - total_paid)
    invoices_count = total_invoiced_res.invoices_count

    overdue_stmt = select(
        func.coalesce(func.sum(Invoice.total_amount - Invoice.paid_amount), 0).label("overdue_amt"),
        func.count(Invoice.id).label("overdue_count"),
    ).where(
        Invoice.organization_id == tenant.organization_id,
        Invoice.due_date < today,
        Invoice.status != InvoiceStatus.PAID,
    )
    overdue_res = (await db.execute(overdue_stmt)).one()
    total_overdue = _as_money(overdue_res.overdue_amt)
    overdue_invoices_count = overdue_res.overdue_count

    total_recovered_stmt = select(func.coalesce(func.sum(Payment.amount), 0)).where(
        Payment.organization_id == tenant.organization_id,
    )
    total_recovered = _as_money((await db.execute(total_recovered_stmt)).scalar_one() or 0)

    amount_in_recovery_stmt = select(func.coalesce(func.sum(Case.amount_in_recovery), 0)).where(
        Case.organization_id == tenant.organization_id,
    )
    total_amount_in_recovery = _as_money((await db.execute(amount_in_recovery_stmt)).scalar_one() or 0)

    promises_stmt = select(
        func.count(PromiseToPay.id).label("total_promises"),
        func.sum(case((PromiseToPay.status == PromiseStatus.PENDING, 1), else_=0)).label("pending_promises"),
        func.sum(case((PromiseToPay.status == PromiseStatus.FULFILLED, 1), else_=0)).label("fulfilled_promises"),
        func.sum(case((PromiseToPay.status == PromiseStatus.BROKEN, 1), else_=0)).label("broken_promises"),
    ).where(PromiseToPay.organization_id == tenant.organization_id)
    promise_res = (await db.execute(promises_stmt)).one()

    actions_stmt = select(func.count(AuditLog.id)).where(
        AuditLog.organization_id == tenant.organization_id,
        AuditLog.entity_type.in_(["RecoveryAction", "Case", "Payment", "PromiseToPay", "Invoice"]),
    )
    actions_count = (await db.execute(actions_stmt)).scalar_one()

    actions_7d_stmt = select(func.count(AuditLog.id)).where(
        AuditLog.organization_id == tenant.organization_id,
        AuditLog.created_at >= window_start,
        AuditLog.entity_type.in_(["RecoveryAction", "Case", "Payment", "PromiseToPay", "Invoice"]),
    )
    last_7_days = (await db.execute(actions_7d_stmt)).scalar_one()

    return RecoveryDashboardSummary(
        cases=CasesSummary(
            total=cases_total,
            active=active_cases,
            resolved=resolved_cases,
        ),
        financial=FinancialSummary(
            total_amount_in_recovery=total_amount_in_recovery,
            total_recovered=total_recovered,
            total_outstanding=total_outstanding,
            total_overdue=total_overdue,
            invoices_count=invoices_count,
            overdue_invoices_count=overdue_invoices_count,
        ),
        promises=PromiseSummary(
            total=promise_res.total_promises or 0,
            pending=promise_res.pending_promises or 0,
            fulfilled=promise_res.fulfilled_promises or 0,
            broken=promise_res.broken_promises or 0,
        ),
        activity=ActivitySummary(
            actions_count=actions_count,
            last_7_days=last_7_days,
        ),
    )


@recovery_router.get("/dashboard/activity", response_model=list[RecoveryActivityItem])
async def get_recovery_activity(
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(AuditLog)
        .where(AuditLog.organization_id == tenant.organization_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(25)
    )
    result = await db.execute(stmt)
    items = result.scalars().all()

    response = []
    for item in items:
        response.append(
            RecoveryActivityItem(
                id=item.id,
                action=item.action,
                entity_type=item.entity_type,
                entity_id=item.entity_id,
                timestamp=item.created_at,
                details=item.details,
                user_id=item.user_id,
            )
        )

    return response


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    today = date.today()

    # Invoices aggregate
    inv_stmt = select(
        func.coalesce(func.sum(Invoice.total_amount), 0).label("total_invoiced"),
        func.coalesce(func.sum(Invoice.paid_amount), 0).label("total_paid"),
        func.count(Invoice.id).label("invoices_count"),
    ).where(Invoice.organization_id == tenant.organization_id)
    inv_res = (await db.execute(inv_stmt)).one()

    total_invoiced = Decimal(str(inv_res.total_invoiced))
    total_paid = Decimal(str(inv_res.total_paid))
    total_outstanding = max(Decimal("0.00"), total_invoiced - total_paid)
    invoices_count = inv_res.invoices_count

    # Overdue aggregate: due_date < today and not fully paid
    overdue_stmt = select(
        func.coalesce(func.sum(Invoice.total_amount - Invoice.paid_amount), 0).label("overdue_amt"),
        func.count(Invoice.id).label("overdue_count"),
    ).where(
        Invoice.organization_id == tenant.organization_id,
        Invoice.due_date < today,
        Invoice.status != InvoiceStatus.PAID,
    )
    overdue_res = (await db.execute(overdue_stmt)).one()
    total_overdue = Decimal(str(overdue_res.overdue_amt))
    overdue_count = overdue_res.overdue_count

    # Active cases count
    cases_stmt = select(func.count(Case.id)).where(
        Case.organization_id == tenant.organization_id,
        Case.status.notin_([CaseStatus.RESOLVED, CaseStatus.CLOSED]),
    )
    active_cases = (await db.execute(cases_stmt)).scalar_one()

    # Customers count
    cust_stmt = select(func.count(Customer.id)).where(
        Customer.organization_id == tenant.organization_id
    )
    cust_count = (await db.execute(cust_stmt)).scalar_one()

    return DashboardSummary(
        total_invoiced=total_invoiced,
        total_paid=total_paid,
        total_outstanding=total_outstanding,
        total_overdue=total_overdue,
        invoices_count=invoices_count,
        overdue_invoices_count=overdue_count,
        active_cases_count=active_cases,
        customers_count=cust_count,
    )
