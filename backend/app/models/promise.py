"""
PromiseToPay model — tracks customer payment promises for recovery workflows.

Each promise represents a commitment by the customer to pay a specific amount by a specific date.
Multiple promises can exist for a single case (e.g., installment plans, re-negotiations).
"""
import enum
from datetime import date
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Text, ForeignKey, Enum as SQLEnum, Numeric, Date
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.case import Case
    from app.models.stubs import Payment


class PromiseStatus(str, enum.Enum):
    """
    Promise lifecycle status.
    
    PENDING: Promise made, date not yet reached
    FULFILLED: Payment received matching or exceeding promise
    BROKEN: Promise date passed without matching payment
    CANCELLED: Promise voided (e.g., customer renegotiated, case escalated)
    """
    PENDING = "PENDING"
    FULFILLED = "FULFILLED"
    BROKEN = "BROKEN"
    CANCELLED = "CANCELLED"


class PromiseToPay(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Customer payment promise for a recovery case.
    
    Supports:
    - Multiple promises per case (e.g., "₹2,500 on Oct 15, ₹2,500 on Nov 15")
    - Promise amendments (customer requests extension)
    - Fulfillment tracking (links to actual Payment record)
    - Broken promise detection (promise_date passed, no matching payment)
    """
    __tablename__ = "promises_to_pay"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
        doc="Tenant isolation — all promises belong to an organization"
    )
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False, index=True,
        doc="Which recovery case this promise belongs to"
    )
    
    promise_date: Mapped[date] = mapped_column(
        Date, nullable=False, index=True,
        doc="When the customer promises to pay"
    )
    promised_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False,
        doc="How much the customer promises to pay"
    )
    status: Mapped[PromiseStatus] = mapped_column(
        SQLEnum(PromiseStatus), default=PromiseStatus.PENDING,
        nullable=False, index=True,
        doc="Promise lifecycle state"
    )
    
    fulfilled_by_payment_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
        doc="If FULFILLED, which payment satisfied this promise"
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        doc="Free-form notes (e.g., 'Customer called, requested 2-week extension')"
    )

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization")
    case: Mapped["Case"] = relationship("Case", back_populates="promises")
    fulfilled_by_payment: Mapped[Optional["Payment"]] = relationship(
        "Payment", foreign_keys=[fulfilled_by_payment_id]
    )
