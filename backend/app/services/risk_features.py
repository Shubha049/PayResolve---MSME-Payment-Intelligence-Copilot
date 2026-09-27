"""
Risk Feature Engineering for PayResolve AI — Phase 4.

Derives 8 features per invoice/customer pair from existing Invoice, Case, and
Customer data already stored in the DB.  No new data sources required.

Feature vector is deterministic and pure — no side effects, testable in isolation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional, Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.case import Case, CaseStatus

logger = logging.getLogger(__name__)

# Minimum number of *settled* invoices before ML scoring is attempted.
ML_HISTORY_THRESHOLD = 5

# Horizon (days) used to normalise invoice_age_days to [0, 1]
AGE_HORIZON_DAYS = 180


@dataclass
class RiskFeatureVector:
    """
    8-feature vector used by both HeuristicScorer and MLScorer.
    All values are Python floats; the ML model receives a list in canonical order.
    """
    # Number of settled (PAID or WRITTEN_OFF) invoices for this customer in this org
    prior_invoice_count: float = 0.0
    # Number of those settled invoices that were paid after the due date
    late_payment_count: float = 0.0
    # Mean days-past-due on settled invoices (0.0 when prior_invoice_count == 0)
    avg_days_late: float = 0.0
    # outstanding_amount / max(1, avg_historical_amount); capped at 2.0
    outstanding_ratio: float = 0.0
    # Count of OVERDUE invoices for this customer right now (capped at 5)
    overdue_invoice_count: float = 0.0
    # open or disputed cases / max(1, total invoice count); capped at 1.0
    dispute_frequency: float = 0.0
    # (today - invoice.issue_date).days; capped at AGE_HORIZON_DAYS
    invoice_age_days: float = 0.0
    # invoice.total_amount / max(1, avg_historical_amount); capped at 3.0
    amount_vs_avg_ratio: float = 1.0

    def to_list(self) -> list[float]:
        """Canonical ML feature order — must match training column order."""
        return [
            self.prior_invoice_count,
            self.late_payment_count,
            self.avg_days_late,
            self.outstanding_ratio,
            self.overdue_invoice_count,
            self.dispute_frequency,
            self.invoice_age_days,
            self.amount_vs_avg_ratio,
        ]

    @classmethod
    def feature_names(cls) -> list[str]:
        return [
            "prior_invoice_count",
            "late_payment_count",
            "avg_days_late",
            "outstanding_ratio",
            "overdue_invoice_count",
            "dispute_frequency",
            "invoice_age_days",
            "amount_vs_avg_ratio",
        ]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def extract_features(
    db: AsyncSession,
    org_id: str,
    customer_id: str,
    invoice: Invoice,
) -> RiskFeatureVector:
    """
    Derive the full feature vector for the given invoice.

    All queries are scoped to (org_id, customer_id) for tenant safety.
    """
    today = date.today()

    # ── 1. Historical settled invoices for this customer ────────────────────
    settled_statuses = [InvoiceStatus.PAID, InvoiceStatus.WRITTEN_OFF]
    settled_stmt = select(Invoice).where(
        Invoice.organization_id == org_id,
        Invoice.customer_id == customer_id,
        Invoice.status.in_(settled_statuses),
        # Exclude the invoice being scored itself
        Invoice.id != invoice.id,
    )
    settled_result = await db.execute(settled_stmt)
    settled_invoices: list[Invoice] = list(settled_result.scalars().all())

    prior_invoice_count = float(len(settled_invoices))

    # Average historical invoice amount (used as denominator for ratios)
    avg_historical_amount: float = 1.0
    if settled_invoices:
        avg_historical_amount = max(
            1.0,
            float(sum(inv.total_amount for inv in settled_invoices)) / len(settled_invoices),
        )

    # Late payment stats — use actual Payment records when available
    # Fallback to invoice updated_at if no payment record exists
    from app.models import Payment
    
    late_count = 0
    total_days_late = 0.0
    for inv in settled_invoices:
        # Try to find actual payment record
        payment_stmt = select(Payment).where(
            Payment.organization_id == org_id,
            Payment.invoice_id == inv.id,
        ).order_by(Payment.payment_date.desc())
        payment_result = await db.execute(payment_stmt)
        payment = payment_result.scalar_one_or_none()
        
        if payment:
            paid_date = payment.payment_date
        else:
            # Fallback: use invoice updated_at as proxy
            paid_date = inv.updated_at.date() if inv.updated_at else inv.due_date
            
        if paid_date > inv.due_date:
            days_late = (paid_date - inv.due_date).days
            late_count += 1
            total_days_late += days_late

    late_payment_count = float(late_count)
    avg_days_late = (total_days_late / late_count) if late_count > 0 else 0.0

    # ── 2. Current outstanding balance ──────────────────────────────────────
    outstanding = float(invoice.outstanding_amount)
    outstanding_ratio = min(2.0, outstanding / avg_historical_amount)

    # ── 3. Currently overdue invoices for this customer ──────────────────────
    overdue_stmt = select(func.count()).select_from(Invoice).where(
        Invoice.organization_id == org_id,
        Invoice.customer_id == customer_id,
        Invoice.status == InvoiceStatus.OVERDUE,
        Invoice.id != invoice.id,
    )
    overdue_count_result = await db.execute(overdue_stmt)
    overdue_invoice_count = float(min(5, overdue_count_result.scalar_one() or 0))

    # ── 4. Dispute frequency ─────────────────────────────────────────────────
    open_dispute_statuses = [CaseStatus.OPEN, CaseStatus.IN_DISPUTE, CaseStatus.ESCALATED]
    dispute_stmt = select(func.count()).select_from(Case).where(
        Case.organization_id == org_id,
        Case.customer_id == customer_id,
        Case.status.in_(open_dispute_statuses),
    )
    total_invoices_stmt = select(func.count()).select_from(Invoice).where(
        Invoice.organization_id == org_id,
        Invoice.customer_id == customer_id,
    )
    dispute_count = (await db.execute(dispute_stmt)).scalar_one() or 0
    total_invoice_count = (await db.execute(total_invoices_stmt)).scalar_one() or 1
    dispute_frequency = min(1.0, dispute_count / max(1, total_invoice_count))

    # ── 5. Invoice age ───────────────────────────────────────────────────────
    invoice_age_days = float(min(AGE_HORIZON_DAYS, (today - invoice.issue_date).days))

    # ── 6. Invoice amount vs. historical average ─────────────────────────────
    amount_vs_avg_ratio = min(
        3.0, float(invoice.total_amount) / avg_historical_amount
    )

    return RiskFeatureVector(
        prior_invoice_count=prior_invoice_count,
        late_payment_count=late_payment_count,
        avg_days_late=avg_days_late,
        outstanding_ratio=outstanding_ratio,
        overdue_invoice_count=overdue_invoice_count,
        dispute_frequency=dispute_frequency,
        invoice_age_days=invoice_age_days,
        amount_vs_avg_ratio=amount_vs_avg_ratio,
    )
