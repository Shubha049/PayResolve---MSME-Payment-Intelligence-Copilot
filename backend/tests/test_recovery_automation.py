from datetime import date, timedelta
from decimal import Decimal
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.case import Case, CaseStatus
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceStatus
from app.models.organization import Organization
from app.models.promise import PromiseStatus, PromiseToPay
from app.models.recovery_action import RecoveryAction
from app.models.stubs import Payment


async def _create_automation_records(db: AsyncSession, org: Organization, customer: Customer):
    today = date.today()
    invoice = Invoice(
        organization_id=org.id,
        customer_id=customer.id,
        invoice_number=f"AUTO-{uuid.uuid4().hex[:8]}",
        issue_date=today - timedelta(days=60),
        due_date=today - timedelta(days=30),
        total_amount=Decimal("120.00"),
        paid_amount=Decimal("20.00"),
        status=InvoiceStatus.PARTIALLY_PAID,
    )
    db.add(invoice)
    await db.flush()

    due_case = Case(
        organization_id=org.id,
        customer_id=customer.id,
        invoice_id=invoice.id,
        case_number=f"AUTO-{uuid.uuid4().hex[:8]}",
        title="Automation case",
        status=CaseStatus.OPEN,
        amount_in_recovery=Decimal("100.00"),
        next_follow_up_date=today,
    )
    db.add(due_case)
    await db.flush()

    overdue_promise = PromiseToPay(
        organization_id=org.id,
        case_id=due_case.id,
        promise_date=today - timedelta(days=1),
        promised_amount=Decimal("40.00"),
        status=PromiseStatus.PENDING,
    )
    broken_promise = PromiseToPay(
        organization_id=org.id,
        case_id=due_case.id,
        promise_date=today - timedelta(days=2),
        promised_amount=Decimal("30.00"),
        status=PromiseStatus.BROKEN,
    )
    payment = Payment(
        organization_id=org.id,
        invoice_id=invoice.id,
        amount=Decimal("20.00"),
        payment_date=today - timedelta(days=5),
        reference="AUTOMATION-TEST",
    )
    db.add_all([overdue_promise, broken_promise, payment])
    await db.commit()
    return invoice, due_case, overdue_promise, broken_promise, payment


@pytest.mark.asyncio
async def test_automation_detects_conditions_is_idempotent_and_audited(
    client: AsyncClient,
    db_session: AsyncSession,
    org: Organization,
    user,
    customer: Customer,
    auth_headers,
):
    invoice, case, overdue, broken, payment = await _create_automation_records(db_session, org, customer)
    before_financials = (invoice.total_amount, invoice.paid_amount, payment.amount, case.amount_in_recovery)

    first = await client.post("/api/v1/recovery/automation/run", headers=auth_headers)
    assert first.status_code == 200, first.text
    assert first.json() == {
        "created_count": 3,
        "promise_overdue": 1,
        "follow_up_due": 1,
        "broken_promise_attention": 1,
    }

    actions = (
        await db_session.execute(select(RecoveryAction).where(RecoveryAction.organization_id == org.id))
    ).scalars().all()
    assert {action.action_type.value for action in actions} == {
        "PROMISE_OVERDUE",
        "FOLLOW_UP_DUE",
        "BROKEN_PROMISE_ATTENTION",
    }
    assert all(action.created_by_user_id == user.id for action in actions)
    assert overdue.status == PromiseStatus.PENDING
    assert broken.status == PromiseStatus.BROKEN

    audit_rows = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.organization_id == org.id,
                AuditLog.action == "RECOVERY_AUTOMATION_ACTION_CREATED",
            )
        )
    ).scalars().all()
    assert len(audit_rows) == 3
    assert {row.entity_id for row in audit_rows} == {action.id for action in actions}

    second = await client.post("/api/v1/recovery/automation/run", headers=auth_headers)
    assert second.status_code == 200, second.text
    assert second.json()["created_count"] == 0
    action_count = await db_session.scalar(
        select(func.count(RecoveryAction.id)).where(RecoveryAction.organization_id == org.id)
    )
    assert action_count == 3
    assert (invoice.total_amount, invoice.paid_amount, payment.amount, case.amount_in_recovery) == before_financials


@pytest.mark.asyncio
async def test_automation_is_tenant_scoped(
    client: AsyncClient,
    db_session: AsyncSession,
    org: Organization,
    customer: Customer,
    auth_headers,
    org2: Organization,
    user2,
):
    await _create_automation_records(db_session, org2, customer)

    response = await client.post("/api/v1/recovery/automation/run", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["created_count"] == 0

    cross_tenant_headers = {
        **auth_headers,
        "X-Organization-Id": org2.id,
    }
    denied = await client.post("/api/v1/recovery/automation/run", headers=cross_tenant_headers)
    assert denied.status_code == 403

    other_tenant_actions = (
        await db_session.execute(select(RecoveryAction).where(RecoveryAction.organization_id == org2.id))
    ).scalars().all()
    assert other_tenant_actions == []