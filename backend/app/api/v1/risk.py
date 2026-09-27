"""
Risk Assessment API — Phase 4.

Endpoints:
  GET  /risk/invoice/{invoice_id}           Latest assessment for an invoice
  GET  /risk/customer/{customer_id}         Latest assessment for a customer (aggregate)
  POST /risk/invoice/{invoice_id}/rescore   Manual rescore trigger
  GET  /risk/invoice/{invoice_id}/history   Full scoring timeline (newest first)

All endpoints enforce org_id == tenant.organization_id.
"""

import asyncio
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.stubs import RiskAssessment
from app.models.invoice import Invoice
from app.models.customer import Customer
from app.schemas.risk import RiskAssessmentRead
from app.api.deps import get_current_tenant, TenantContext
from app.services.risk_service import score_invoice, score_customer_aggregate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/risk", tags=["Risk"])


def _tenant_check_assessment(assessment: RiskAssessment, org_id: str) -> None:
    """Raise 404 if the assessment doesn't belong to this org."""
    if assessment.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


# ── GET /risk/invoice/{invoice_id} ───────────────────────────────────────────

@router.get("/invoice/{invoice_id}", response_model=RiskAssessmentRead)
async def get_invoice_risk(
    invoice_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the most recent risk assessment for an invoice.
    If none exists yet, triggers a fresh score and returns it.
    """
    # Verify invoice belongs to this org
    inv_stmt = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.organization_id == tenant.organization_id,
    )
    invoice = (await db.execute(inv_stmt)).scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    # Fetch latest assessment
    assess_stmt = (
        select(RiskAssessment)
        .where(
            RiskAssessment.invoice_id == invoice_id,
            RiskAssessment.organization_id == tenant.organization_id,
        )
        .order_by(RiskAssessment.created_at.desc())
        .limit(1)
    )
    assessment = (await db.execute(assess_stmt)).scalar_one_or_none()

    if assessment is None:
        # Score on-demand if no prior assessment exists
        assessment = await score_invoice(db, tenant.organization_id, invoice_id)
        if assessment is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate risk score",
            )

    return assessment


# ── GET /risk/customer/{customer_id} ─────────────────────────────────────────

@router.get("/customer/{customer_id}", response_model=RiskAssessmentRead)
async def get_customer_risk(
    customer_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the most recent aggregate risk assessment for a customer.
    On-demand scoring if none exists.
    """
    cust_stmt = select(Customer).where(
        Customer.id == customer_id,
        Customer.organization_id == tenant.organization_id,
    )
    customer = (await db.execute(cust_stmt)).scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    assess_stmt = (
        select(RiskAssessment)
        .where(
            RiskAssessment.customer_id == customer_id,
            RiskAssessment.organization_id == tenant.organization_id,
        )
        .order_by(RiskAssessment.created_at.desc())
        .limit(1)
    )
    assessment = (await db.execute(assess_stmt)).scalar_one_or_none()

    if assessment is None:
        assessment = await score_customer_aggregate(db, tenant.organization_id, customer_id)
        if assessment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No invoices found for this customer to score against",
            )

    return assessment


# ── POST /risk/invoice/{invoice_id}/rescore ──────────────────────────────────

@router.post(
    "/invoice/{invoice_id}/rescore",
    response_model=RiskAssessmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def rescore_invoice(
    invoice_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger a new scoring event. Returns the new assessment row."""
    # Verify invoice belongs to this org
    inv_stmt = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.organization_id == tenant.organization_id,
    )
    invoice = (await db.execute(inv_stmt)).scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    assessment = await score_invoice(db, tenant.organization_id, invoice_id)
    if assessment is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate risk score",
        )
    return assessment


# ── GET /risk/invoice/{invoice_id}/history ───────────────────────────────────

@router.get("/invoice/{invoice_id}/history", response_model=List[RiskAssessmentRead])
async def get_invoice_risk_history(
    invoice_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Return full scoring timeline for an invoice, newest first."""
    # Verify invoice belongs to this org
    inv_stmt = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.organization_id == tenant.organization_id,
    )
    invoice = (await db.execute(inv_stmt)).scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    history_stmt = (
        select(RiskAssessment)
        .where(
            RiskAssessment.invoice_id == invoice_id,
            RiskAssessment.organization_id == tenant.organization_id,
        )
        .order_by(RiskAssessment.created_at.desc())
    )
    results = (await db.execute(history_stmt)).scalars().all()
    return list(results)
