"""
Phase 1 Recovery Workflow Model Tests.

Tests the new Case recovery fields and PromiseToPay model.
Does NOT test APIs (those come in later phases).
"""
import pytest
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Organization,
    Customer,
    Invoice,
    InvoiceStatus,
    Case,
    CaseStatus,
    CasePriority,
    Payment,
    PromiseToPay,
    PromiseStatus,
)


@pytest.mark.asyncio
async def test_case_with_recovery_fields(db_session: AsyncSession):
    """Case can be created with all four new recovery fields."""
    db = db_session
    
    # Create organization and customer
    org = Organization(name="Recovery Test Org", slug="recovery-test")
    db.add(org)
    await db.flush()
    
    customer = Customer(
        organization_id=org.id,
        name="Test Customer",
        email="customer@test.com",
    )
    db.add(customer)
    await db.flush()
    
    # Create case with recovery fields
    case = Case(
        organization_id=org.id,
        customer_id=customer.id,
        case_number="REC-001",
        title="Recovery Test Case",
        status=CaseStatus.OPEN,
        priority=CasePriority.HIGH,
        # Recovery fields
        amount_in_recovery=Decimal("5000.00"),
        expected_payment_date=date.today() + timedelta(days=7),
        last_contact_date=date.today(),
        next_follow_up_date=date.today() + timedelta(days=3),
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    
    # Verify all fields saved correctly
    assert case.amount_in_recovery == Decimal("5000.00")
    assert case.expected_payment_date == date.today() + timedelta(days=7)
    assert case.last_contact_date == date.today()
    assert case.next_follow_up_date == date.today() + timedelta(days=3)


@pytest.mark.asyncio
async def test_case_without_recovery_fields(db_session: AsyncSession):
    """Case can be created without recovery fields (backward compatibility)."""
    db = db_session
    
    org = Organization(name="Compat Test Org", slug="compat-test")
    db.add(org)
    await db.flush()
    
    customer = Customer(
        organization_id=org.id,
        name="Compat Customer",
        email="compat@test.com",
    )
    db.add(customer)
    await db.flush()
    
    # Create case WITHOUT recovery fields
    case = Case(
        organization_id=org.id,
        customer_id=customer.id,
        case_number="CASE-001",
        title="Normal Case",
        status=CaseStatus.OPEN,
        priority=CasePriority.MEDIUM,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    
    # Verify all recovery fields are None
    assert case.amount_in_recovery is None
    assert case.expected_payment_date is None
    assert case.last_contact_date is None
    assert case.next_follow_up_date is None


@pytest.mark.asyncio
async def test_promise_to_pay_creation(db_session: AsyncSession):
    """PromiseToPay can be created and linked to a case."""
    db = db_session
    
    org = Organization(name="Promise Test Org", slug="promise-test")
    db.add(org)
    await db.flush()
    
    customer = Customer(
        organization_id=org.id,
        name="Promise Customer",
        email="promise@test.com",
    )
    db.add(customer)
    await db.flush()
    
    case = Case(
        organization_id=org.id,
        customer_id=customer.id,
        case_number="PROM-001",
        title="Promise Test Case",
        status=CaseStatus.REMINDER_SENT,
    )
    db.add(case)
    await db.flush()
    
    # Create promise
    promise = PromiseToPay(
        organization_id=org.id,
        case_id=case.id,
        promise_date=date.today() + timedelta(days=10),
        promised_amount=Decimal("2500.00"),
        status=PromiseStatus.PENDING,
        notes="Customer called, agreed to payment",
    )
    db.add(promise)
    await db.commit()
    await db.refresh(promise)
    
    # Verify promise saved correctly
    assert promise.promise_date == date.today() + timedelta(days=10)
    assert promise.promised_amount == Decimal("2500.00")
    assert promise.status == PromiseStatus.PENDING
    assert promise.notes == "Customer called, agreed to payment"
    assert promise.fulfilled_by_payment_id is None


@pytest.mark.asyncio
async def test_promise_status_lifecycle(db_session: AsyncSession):
    """Promise status can transition through its lifecycle."""
    db = db_session
    
    org = Organization(name="Lifecycle Org", slug="lifecycle-test")
    db.add(org)
    await db.flush()
    
    customer = Customer(organization_id=org.id, name="Lifecycle Customer", email="lifecycle@test.com")
    db.add(customer)
    await db.flush()
    
    case = Case(
        organization_id=org.id,
        customer_id=customer.id,
        case_number="LIFE-001",
        title="Lifecycle Case",
    )
    db.add(case)
    await db.flush()
    
    # Create promise
    promise = PromiseToPay(
        organization_id=org.id,
        case_id=case.id,
        promise_date=date.today() + timedelta(days=5),
        promised_amount=Decimal("1000.00"),
        status=PromiseStatus.PENDING,
    )
    db.add(promise)
    await db.commit()
    
    # Test PENDING → FULFILLED
    promise.status = PromiseStatus.FULFILLED
    await db.commit()
    await db.refresh(promise)
    assert promise.status == PromiseStatus.FULFILLED
    
    # Create new promise and test PENDING → BROKEN
    promise2 = PromiseToPay(
        organization_id=org.id,
        case_id=case.id,
        promise_date=date.today() - timedelta(days=5),  # Past date
        promised_amount=Decimal("500.00"),
        status=PromiseStatus.PENDING,
    )
    db.add(promise2)
    await db.commit()
    
    promise2.status = PromiseStatus.BROKEN
    await db.commit()
    await db.refresh(promise2)
    assert promise2.status == PromiseStatus.BROKEN


@pytest.mark.asyncio
async def test_promise_linked_to_payment(db_session: AsyncSession):
    """Promise can be linked to a Payment that fulfilled it."""
    db = db_session
    
    org = Organization(name="Payment Link Org", slug="payment-link")
    db.add(org)
    await db.flush()
    
    customer = Customer(organization_id=org.id, name="Pay Customer", email="pay@test.com")
    db.add(customer)
    await db.flush()
    
    invoice = Invoice(
        organization_id=org.id,
        customer_id=customer.id,
        invoice_number="INV-PAY-001",
        issue_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        total_amount=Decimal("3000.00"),
        status=InvoiceStatus.OVERDUE,
    )
    db.add(invoice)
    await db.flush()
    
    case = Case(
        organization_id=org.id,
        customer_id=customer.id,
        invoice_id=invoice.id,
        case_number="PAY-001",
        title="Payment Link Case",
    )
    db.add(case)
    await db.flush()
    
    # Create promise
    promise = PromiseToPay(
        organization_id=org.id,
        case_id=case.id,
        promise_date=date.today(),
        promised_amount=Decimal("3000.00"),
        status=PromiseStatus.PENDING,
    )
    db.add(promise)
    await db.flush()
    
    # Create payment
    payment = Payment(
        organization_id=org.id,
        invoice_id=invoice.id,
        amount=Decimal("3000.00"),
        payment_date=date.today(),
        reference="TXN-12345",
    )
    db.add(payment)
    await db.flush()
    
    # Link promise to payment
    promise.status = PromiseStatus.FULFILLED
    promise.fulfilled_by_payment_id = payment.id
    await db.commit()
    await db.refresh(promise)
    
    # Verify linkage
    assert promise.fulfilled_by_payment_id == payment.id
    assert promise.status == PromiseStatus.FULFILLED


@pytest.mark.asyncio
async def test_multiple_promises_per_case(db_session: AsyncSession):
    """Multiple promises can exist for a single case (e.g., installment plan)."""
    db = db_session
    
    org = Organization(name="Multi Promise Org", slug="multi-promise")
    db.add(org)
    await db.flush()
    
    customer = Customer(organization_id=org.id, name="Multi Customer", email="multi@test.com")
    db.add(customer)
    await db.flush()
    
    case = Case(
        organization_id=org.id,
        customer_id=customer.id,
        case_number="MULTI-001",
        title="Installment Plan Case",
        amount_in_recovery=Decimal("5000.00"),
    )
    db.add(case)
    await db.flush()
    
    # Create three promises (installment plan)
    promise1 = PromiseToPay(
        organization_id=org.id,
        case_id=case.id,
        promise_date=date.today() + timedelta(days=10),
        promised_amount=Decimal("2000.00"),
        status=PromiseStatus.PENDING,
        notes="First installment",
    )
    promise2 = PromiseToPay(
        organization_id=org.id,
        case_id=case.id,
        promise_date=date.today() + timedelta(days=40),
        promised_amount=Decimal("2000.00"),
        status=PromiseStatus.PENDING,
        notes="Second installment",
    )
    promise3 = PromiseToPay(
        organization_id=org.id,
        case_id=case.id,
        promise_date=date.today() + timedelta(days=70),
        promised_amount=Decimal("1000.00"),
        status=PromiseStatus.PENDING,
        notes="Final installment",
    )
    db.add_all([promise1, promise2, promise3])
    await db.commit()
    
    # Verify all promises linked to case - need to eager load
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    stmt = select(Case).where(Case.id == case.id).options(selectinload(Case.promises))
    result = await db.execute(stmt)
    case_with_promises = result.scalar_one()
    
    assert len(case_with_promises.promises) == 3
    assert sum(p.promised_amount for p in case_with_promises.promises) == Decimal("5000.00")


@pytest.mark.asyncio
async def test_case_relationship_loads_promises(db_session: AsyncSession):
    """Case.promises relationship loads correctly."""
    db = db_session
    
    org = Organization(name="Relationship Org", slug="rel-test")
    db.add(org)
    await db.flush()
    
    customer = Customer(organization_id=org.id, name="Rel Customer", email="rel@test.com")
    db.add(customer)
    await db.flush()
    
    case = Case(
        organization_id=org.id,
        customer_id=customer.id,
        case_number="REL-001",
        title="Relationship Test",
    )
    db.add(case)
    await db.flush()
    
    promise = PromiseToPay(
        organization_id=org.id,
        case_id=case.id,
        promise_date=date.today() + timedelta(days=5),
        promised_amount=Decimal("1500.00"),
        status=PromiseStatus.PENDING,
    )
    db.add(promise)
    await db.commit()
    
    # Reload case and verify promises relationship - need to eager load
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    stmt = select(Case).where(Case.id == case.id).options(selectinload(Case.promises))
    result = await db.execute(stmt)
    case_with_promises = result.scalar_one()
    
    assert len(case_with_promises.promises) == 1
    assert case_with_promises.promises[0].id == promise.id
    assert case_with_promises.promises[0].promised_amount == Decimal("1500.00")


@pytest.mark.asyncio
async def test_tenant_isolation_promises(db_session: AsyncSession):
    """Promises are isolated by organization_id (tenant isolation)."""
    db = db_session
    
    # Create two organizations
    org_a = Organization(name="Org A", slug="org-a")
    org_b = Organization(name="Org B", slug="org-b")
    db.add_all([org_a, org_b])
    await db.flush()
    
    # Create customers and cases in each org
    cust_a = Customer(organization_id=org_a.id, name="Customer A", email="a@test.com")
    cust_b = Customer(organization_id=org_b.id, name="Customer B", email="b@test.com")
    db.add_all([cust_a, cust_b])
    await db.flush()
    
    case_a = Case(
        organization_id=org_a.id,
        customer_id=cust_a.id,
        case_number="CASE-A",
        title="Case A",
    )
    case_b = Case(
        organization_id=org_b.id,
        customer_id=cust_b.id,
        case_number="CASE-B",
        title="Case B",
    )
    db.add_all([case_a, case_b])
    await db.flush()
    
    # Create promises in each org
    promise_a = PromiseToPay(
        organization_id=org_a.id,
        case_id=case_a.id,
        promise_date=date.today(),
        promised_amount=Decimal("1000.00"),
        status=PromiseStatus.PENDING,
    )
    promise_b = PromiseToPay(
        organization_id=org_b.id,
        case_id=case_b.id,
        promise_date=date.today(),
        promised_amount=Decimal("2000.00"),
        status=PromiseStatus.PENDING,
    )
    db.add_all([promise_a, promise_b])
    await db.commit()
    
    # Verify promises belong to correct orgs
    assert promise_a.organization_id == org_a.id
    assert promise_b.organization_id == org_b.id
    
    # Verify cases only see their own promises - need to eager load
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    
    stmt_a = select(Case).where(Case.id == case_a.id).options(selectinload(Case.promises))
    stmt_b = select(Case).where(Case.id == case_b.id).options(selectinload(Case.promises))
    
    result_a = await db.execute(stmt_a)
    result_b = await db.execute(stmt_b)
    
    case_a_loaded = result_a.scalar_one()
    case_b_loaded = result_b.scalar_one()
    
    assert len(case_a_loaded.promises) == 1
    assert case_a_loaded.promises[0].id == promise_a.id
    assert len(case_b_loaded.promises) == 1
    assert case_b_loaded.promises[0].id == promise_b.id


@pytest.mark.asyncio
async def test_case_cascade_deletes_promises(db_session: AsyncSession):
    """Deleting a case cascades to delete its promises."""
    db = db_session
    
    org = Organization(name="Cascade Org", slug="cascade-test")
    db.add(org)
    await db.flush()
    
    customer = Customer(organization_id=org.id, name="Cascade Customer", email="cascade@test.com")
    db.add(customer)
    await db.flush()
    
    case = Case(
        organization_id=org.id,
        customer_id=customer.id,
        case_number="CASCADE-001",
        title="Cascade Test",
    )
    db.add(case)
    await db.flush()
    
    promise = PromiseToPay(
        organization_id=org.id,
        case_id=case.id,
        promise_date=date.today(),
        promised_amount=Decimal("1000.00"),
        status=PromiseStatus.PENDING,
    )
    db.add(promise)
    await db.commit()
    promise_id = promise.id
    
    # Delete case
    await db.delete(case)
    await db.commit()
    
    # Verify promise was cascade deleted
    from sqlalchemy import select
    stmt = select(PromiseToPay).where(PromiseToPay.id == promise_id)
    result = await db.execute(stmt)
    deleted_promise = result.scalar_one_or_none()
    assert deleted_promise is None
