from datetime import date
from typing import List, Optional
import asyncio
import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.invoice import Invoice, InvoiceStatus
from app.models.customer import Customer
from app.schemas.invoice import InvoiceCreate, InvoiceUpdate, InvoiceRead
from app.api.deps import get_current_tenant, TenantContext
from app.services.audit_service import log_audit_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/invoices", tags=["Invoices"])


async def _rescore_invoice(org_id: str, invoice_id: str) -> None:
    """
    Fire-and-forget background risk rescoring.
    Creates its own DB session to avoid using the closed request session.
    Wraps score_invoice in a Task; logs but does not propagate failures.
    """
    from app.services.risk_service import score_invoice as _score
    from app.database import async_session_factory

    try:
        async with async_session_factory() as session:
            await _score(session, org_id, invoice_id)
            await session.commit()
    except Exception as exc:
        logger.warning("Background risk rescoring failed for invoice %s: %s", invoice_id, exc)


def _fire_rescore(background_tasks: BackgroundTasks, org_id: str, invoice_id: str) -> None:
    background_tasks.add_task(_rescore_invoice, org_id, invoice_id)




@router.get("/", response_model=List[InvoiceRead])
async def list_invoices(
    status_filter: Optional[InvoiceStatus] = Query(None, alias="status"),
    customer_id: Optional[str] = None,
    is_overdue: Optional[bool] = None,
    search: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Invoice)
        .where(Invoice.organization_id == tenant.organization_id)
        .options(selectinload(Invoice.customer))
        .order_by(Invoice.due_date.asc())
        .offset(offset)
        .limit(limit)
    )

    if status_filter:
        stmt = stmt.where(Invoice.status == status_filter)
    if customer_id:
        stmt = stmt.where(Invoice.customer_id == customer_id)
    if search:
        stmt = stmt.where(Invoice.invoice_number.ilike(f"%{search}%"))
    if is_overdue is True:
        today = date.today()
        stmt = stmt.where(
            Invoice.due_date < today,
            Invoice.status.in_([InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.OVERDUE]),
        )

    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/", response_model=InvoiceRead, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    payload: InvoiceCreate,
    background_tasks: BackgroundTasks,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    # Verify customer belongs to this organization
    cust_stmt = select(Customer).where(
        Customer.id == payload.customer_id,
        Customer.organization_id == tenant.organization_id,
    )
    cust_res = await db.execute(cust_stmt)
    customer = cust_res.scalar_one_or_none()
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found in this organization",
        )

    # Check duplicate invoice number within organization
    dup_stmt = select(Invoice).where(
        Invoice.organization_id == tenant.organization_id,
        Invoice.invoice_number == payload.invoice_number,
    )
    dup_res = await db.execute(dup_stmt)
    if dup_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An invoice with this invoice number already exists",
        )

    # Auto-flag status as OVERDUE if due_date < today and status is ISSUED
    initial_status = payload.status
    if payload.due_date < date.today() and initial_status == InvoiceStatus.ISSUED:
        initial_status = InvoiceStatus.OVERDUE

    invoice = Invoice(
        organization_id=tenant.organization_id,
        customer_id=payload.customer_id,
        invoice_number=payload.invoice_number,
        issue_date=payload.issue_date,
        due_date=payload.due_date,
        currency=payload.currency,
        total_amount=payload.total_amount,
        paid_amount=payload.paid_amount,
        status=initial_status,
        notes=payload.notes,
    )
    db.add(invoice)
    await db.flush()

    await log_audit_event(
        db,
        organization_id=tenant.organization_id,
        user_id=tenant.user.id,
        action="INVOICE_CREATED",
        entity_type="Invoice",
        entity_id=invoice.id,
        details={
            "invoice_number": invoice.invoice_number,
            "total_amount": str(invoice.total_amount),
            "status": invoice.status.value,
        },
    )

    await db.commit()

    # Re-fetch with customer eager loaded
    stmt = (
        select(Invoice)
        .where(Invoice.id == invoice.id)
        .options(selectinload(Invoice.customer))
    )
    res = await db.execute(stmt)
    result_invoice = res.scalar_one()

    # Background risk rescoring — non-blocking, errors are logged but not raised
    _fire_rescore(background_tasks, tenant.organization_id, invoice.id)

    return result_invoice


@router.get("/{invoice_id}", response_model=InvoiceRead)
async def get_invoice(
    invoice_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Invoice)
        .where(
            Invoice.id == invoice_id,
            Invoice.organization_id == tenant.organization_id,
        )
        .options(selectinload(Invoice.customer))
    )
    res = await db.execute(stmt)
    invoice = res.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    return invoice


@router.patch("/{invoice_id}", response_model=InvoiceRead)
async def update_invoice(
    invoice_id: str,
    payload: InvoiceUpdate,
    background_tasks: BackgroundTasks,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Invoice)
        .where(
            Invoice.id == invoice_id,
            Invoice.organization_id == tenant.organization_id,
        )
        .options(selectinload(Invoice.customer))
    )
    res = await db.execute(stmt)
    invoice = res.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    update_data = payload.model_dump(exclude_unset=True)
    if "customer_id" in update_data and update_data["customer_id"]:
        # Verify customer in this org
        cust = await db.execute(
            select(Customer).where(
                Customer.id == update_data["customer_id"],
                Customer.organization_id == tenant.organization_id,
            )
        )
        if not cust.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    for field, val in update_data.items():
        setattr(invoice, field, val)

    # Automatically set status to PAID if paid_amount >= total_amount
    if invoice.paid_amount >= invoice.total_amount and invoice.status != InvoiceStatus.PAID:
        invoice.status = InvoiceStatus.PAID

    await log_audit_event(
        db,
        organization_id=tenant.organization_id,
        user_id=tenant.user.id,
        action="INVOICE_UPDATED",
        entity_type="Invoice",
        entity_id=invoice.id,
        details={k: str(v) for k, v in update_data.items()},
    )

    await db.commit()
    await db.refresh(invoice)

    # Background risk rescoring after payment update
    _fire_rescore(background_tasks, tenant.organization_id, invoice_id)

    return invoice


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invoice(
    invoice_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.organization_id == tenant.organization_id,
    )
    res = await db.execute(stmt)
    invoice = res.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    await log_audit_event(
        db,
        organization_id=tenant.organization_id,
        user_id=tenant.user.id,
        action="INVOICE_DELETED",
        entity_type="Invoice",
        entity_id=invoice.id,
        details={"invoice_number": invoice.invoice_number},
    )

    await db.delete(invoice)
    await db.commit()
    return None
