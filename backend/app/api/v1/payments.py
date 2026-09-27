"""Payment API endpoints for recording payments against invoices."""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import date

from app.api.deps import get_db, get_current_tenant, TenantContext
from app.models.stubs import Payment
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.payment import PaymentCreate, PaymentRead, PaymentListResponse
from app.services.audit_service import log_audit_event

router = APIRouter()


@router.post("/", response_model=PaymentRead, status_code=status.HTTP_201_CREATED)
async def create_payment(
    payment_in: PaymentCreate,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new payment against an invoice.
    
    Validates:
    - Amount must be positive (enforced by schema)
    - Invoice must exist and belong to the authenticated organization
    
    Updates:
    - Invoice.paid_amount (cumulative)
    - Invoice.status (auto-set to PAID if paid_amount >= total_amount)
    
    Creates audit log entry.
    """
    # Validate invoice exists and belongs to organization
    stmt = select(Invoice).where(
        Invoice.id == payment_in.invoice_id,
        Invoice.organization_id == tenant.organization_id
    )
    result = await db.execute(stmt)
    invoice = result.scalar_one_or_none()
    
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice {payment_in.invoice_id} not found or does not belong to your organization"
        )
    
    # Create payment
    payment = Payment(
        organization_id=tenant.organization_id,
        invoice_id=payment_in.invoice_id,
        amount=payment_in.amount,
        payment_date=payment_in.payment_date,
        reference=payment_in.reference,
    )
    db.add(payment)
    await db.flush()  # Flush to get payment.id
    
    # Update invoice paid_amount (cumulative)
    invoice.paid_amount += payment_in.amount
    
    # Auto-set status to PAID if fully paid (following existing pattern from invoices.py)
    if invoice.paid_amount >= invoice.total_amount and invoice.status != InvoiceStatus.PAID:
        invoice.status = InvoiceStatus.PAID
    
    # Audit log for payment creation
    await log_audit_event(
        db,
        organization_id=tenant.organization_id,
        user_id=tenant.user.id,
        action="PAYMENT_CREATED",
        entity_type="Payment",
        entity_id=payment.id,
        details={
            "invoice_id": payment_in.invoice_id,
            "amount": str(payment_in.amount),
            "payment_date": payment_in.payment_date.isoformat(),
            "reference": payment_in.reference,
        }
    )
    
    # Audit log for invoice update
    await log_audit_event(
        db,
        organization_id=tenant.organization_id,
        user_id=tenant.user.id,
        action="INVOICE_UPDATED",
        entity_type="Invoice",
        entity_id=invoice.id,
        details={
            "paid_amount": str(invoice.paid_amount),
            "status": invoice.status.value if invoice.paid_amount >= invoice.total_amount else None,
            "reason": "payment_recorded"
        }
    )
    
    await db.commit()
    await db.refresh(payment)
    
    return payment


@router.get("/", response_model=PaymentListResponse)
async def list_payments(
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
    invoice_id: Optional[str] = Query(None, description="Filter by invoice ID (UUID)"),
    from_date: Optional[date] = Query(None, description="Filter payments from this date (inclusive)"),
    to_date: Optional[date] = Query(None, description="Filter payments to this date (inclusive)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=500, description="Number of records to return"),
):
    """
    List payments for the authenticated organization.
    
    Supports filtering by invoice_id and date range.
    Enforces tenant isolation.
    """
    # Build base query with tenant isolation
    stmt = select(Payment).where(Payment.organization_id == tenant.organization_id)
    
    # Apply filters
    if invoice_id is not None:
        stmt = stmt.where(Payment.invoice_id == invoice_id)
    if from_date is not None:
        stmt = stmt.where(Payment.payment_date >= from_date)
    if to_date is not None:
        stmt = stmt.where(Payment.payment_date <= to_date)
    
    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = await db.scalar(count_stmt)
    
    # Apply pagination and ordering
    stmt = stmt.order_by(Payment.payment_date.desc(), Payment.id.desc()).offset(skip).limit(limit)
    
    result = await db.execute(stmt)
    payments = result.scalars().all()
    
    return PaymentListResponse(payments=list(payments), total=total or 0)


@router.get("/{payment_id}", response_model=PaymentRead)
async def get_payment(
    payment_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve a single payment by ID.
    
    Enforces tenant isolation.
    """
    stmt = select(Payment).where(
        Payment.id == payment_id,
        Payment.organization_id == tenant.organization_id
    )
    result = await db.execute(stmt)
    payment = result.scalar_one_or_none()
    
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment {payment_id} not found or does not belong to your organization"
        )
    
    return payment
