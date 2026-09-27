"""
Background Risk Rescoring Service — PayResolve AI Phase 4.

Provides hooks and utilities to trigger automatic risk rescoring when
payment-relevant events occur (new payment, invoice goes overdue, etc.).

In production, this would integrate with:
  - Celery/RQ for async task queuing
  - Database triggers or event listeners
  - Webhook handlers

For this implementation, we provide:
  - Synchronous rescoring functions that can be called from API endpoints
  - Event trigger detection logic
  - Batch rescoring utilities
"""

import logging
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.stubs import Payment, RiskAssessment
from app.services.risk_service import score_invoice

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Event-Triggered Rescoring
# ══════════════════════════════════════════════════════════════════════════════

async def rescore_on_payment(
    db: AsyncSession,
    org_id: str,
    payment: Payment,
) -> Optional[RiskAssessment]:
    """
    Trigger rescoring when a new payment is recorded.
    
    This should be called after a Payment row is created or updated.
    Rescores the associated invoice and returns the new assessment.
    """
    try:
        logger.info(
            "Payment event detected for invoice %s — triggering rescore",
            payment.invoice_id
        )
        assessment = await score_invoice(db, org_id, payment.invoice_id)
        if assessment:
            logger.info(
                "Rescored invoice %s: score=%.2f, category=%s, method=%s",
                payment.invoice_id,
                assessment.risk_score,
                assessment.risk_category,
                assessment.scoring_method,
            )
        return assessment
    except Exception as exc:
        logger.error("Failed to rescore after payment event: %s", exc)
        return None


async def rescore_on_status_change(
    db: AsyncSession,
    org_id: str,
    invoice_id: str,
    old_status: InvoiceStatus,
    new_status: InvoiceStatus,
) -> Optional[RiskAssessment]:
    """
    Trigger rescoring when an invoice status changes.
    
    Particularly important for transitions like:
      - PENDING → OVERDUE
      - OVERDUE → PAID
      - PENDING → DISPUTED
    """
    # Only rescore if status change is meaningful for risk
    significant_transitions = {
        (InvoiceStatus.PENDING, InvoiceStatus.OVERDUE),
        (InvoiceStatus.OVERDUE, InvoiceStatus.PAID),
        (InvoiceStatus.OVERDUE, InvoiceStatus.PARTIALLY_PAID),
        (InvoiceStatus.PENDING, InvoiceStatus.DISPUTED),
        (InvoiceStatus.DISPUTED, InvoiceStatus.RESOLVED),
    }
    
    if (old_status, new_status) not in significant_transitions:
        logger.debug(
            "Status change %s → %s not significant for risk, skipping rescore",
            old_status,
            new_status,
        )
        return None
    
    try:
        logger.info(
            "Invoice %s status changed %s → %s — triggering rescore",
            invoice_id,
            old_status,
            new_status,
        )
        assessment = await score_invoice(db, org_id, invoice_id)
        if assessment:
            logger.info(
                "Rescored invoice %s: score=%.2f, category=%s",
                invoice_id,
                assessment.risk_score,
                assessment.risk_category,
            )
        return assessment
    except Exception as exc:
        logger.error("Failed to rescore after status change: %s", exc)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Batch Rescoring Utilities
# ══════════════════════════════════════════════════════════════════════════════

async def rescore_customer_invoices(
    db: AsyncSession,
    org_id: str,
    customer_id: str,
    limit: Optional[int] = None,
) -> List[RiskAssessment]:
    """
    Rescore all (or limited number of) open/overdue invoices for a customer.
    
    Useful when:
      - Customer payment pattern changes significantly
      - New dispute is filed
      - Manual rescore requested
    """
    stmt = (
        select(Invoice)
        .where(
            Invoice.organization_id == org_id,
            Invoice.customer_id == customer_id,
            Invoice.status.in_([InvoiceStatus.PENDING, InvoiceStatus.OVERDUE]),
        )
        .order_by(Invoice.due_date.asc())
    )
    
    if limit:
        stmt = stmt.limit(limit)
    
    result = await db.execute(stmt)
    invoices = result.scalars().all()
    
    assessments = []
    for invoice in invoices:
        try:
            assessment = await score_invoice(db, org_id, invoice.id)
            if assessment:
                assessments.append(assessment)
        except Exception as exc:
            logger.warning(
                "Failed to rescore invoice %s for customer %s: %s",
                invoice.id,
                customer_id,
                exc,
            )
    
    logger.info(
        "Batch rescored %d/%d invoices for customer %s",
        len(assessments),
        len(invoices),
        customer_id,
    )
    return assessments


async def rescore_overdue_invoices(
    db: AsyncSession,
    org_id: str,
    limit: Optional[int] = None,
) -> List[RiskAssessment]:
    """
    Rescore all (or limited number of) overdue invoices for an organization.
    
    Can be run as a scheduled job (e.g., daily) to keep risk scores fresh.
    """
    stmt = (
        select(Invoice)
        .where(
            Invoice.organization_id == org_id,
            Invoice.status == InvoiceStatus.OVERDUE,
        )
        .order_by(Invoice.due_date.asc())
    )
    
    if limit:
        stmt = stmt.limit(limit)
    
    result = await db.execute(stmt)
    invoices = result.scalars().all()
    
    assessments = []
    for invoice in invoices:
        try:
            assessment = await score_invoice(db, org_id, invoice.id)
            if assessment:
                assessments.append(assessment)
        except Exception as exc:
            logger.warning(
                "Failed to rescore overdue invoice %s: %s",
                invoice.id,
                exc,
            )
    
    logger.info(
        "Batch rescored %d/%d overdue invoices for org %s",
        len(assessments),
        len(invoices),
        org_id,
    )
    return assessments


# ══════════════════════════════════════════════════════════════════════════════
# Helper: Detect if Rescoring is Needed
# ══════════════════════════════════════════════════════════════════════════════

async def should_rescore(
    db: AsyncSession,
    org_id: str,
    invoice_id: str,
    threshold_hours: int = 24,
) -> bool:
    """
    Check if an invoice should be rescored based on age of last assessment.
    
    Returns True if:
      - No prior assessment exists
      - Last assessment is older than threshold_hours
    
    Use this to avoid excessive rescoring on rapid updates.
    """
    from datetime import datetime, timedelta, timezone
    
    stmt = (
        select(RiskAssessment)
        .where(
            RiskAssessment.invoice_id == invoice_id,
            RiskAssessment.organization_id == org_id,
        )
        .order_by(RiskAssessment.created_at.desc())
        .limit(1)
    )
    
    result = await db.execute(stmt)
    latest = result.scalar_one_or_none()
    
    if not latest:
        return True  # No assessment exists
    
    age = datetime.now(timezone.utc) - latest.created_at
    return age > timedelta(hours=threshold_hours)
