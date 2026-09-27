import enum
from datetime import date
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Text, ForeignKey, Enum as SQLEnum, UniqueConstraint, Numeric, Date
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.customer import Customer
    from app.models.invoice import Invoice
    from app.models.user import User
    from app.models.promise import PromiseToPay
    from app.models.recovery_action import RecoveryAction


class CaseStatus(str, enum.Enum):
    OPEN = "OPEN"
    EVIDENCE_GATHERING = "EVIDENCE_GATHERING"
    REMINDER_SENT = "REMINDER_SENT"
    IN_DISPUTE = "IN_DISPUTE"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class CasePriority(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Case(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "cases"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    invoice_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True, index=True
    )
    case_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[CaseStatus] = mapped_column(
        SQLEnum(CaseStatus), default=CaseStatus.OPEN, nullable=False, index=True
    )
    priority: Mapped[CasePriority] = mapped_column(
        SQLEnum(CasePriority), default=CasePriority.MEDIUM, nullable=False
    )
    assigned_to_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Recovery workflow fields (Phase 1)
    amount_in_recovery: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True,
        doc="Total amount being collected in this recovery case"
    )
    expected_payment_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, index=True,
        doc="Customer's promised payment date (latest active promise)"
    )
    last_contact_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True,
        doc="When we last contacted the customer (for compliance/cadence tracking)"
    )
    next_follow_up_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, index=True,
        doc="When to follow up next (task queue driver)"
    )

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization", back_populates="cases")
    customer: Mapped["Customer"] = relationship("Customer", back_populates="cases")
    invoice: Mapped[Optional["Invoice"]] = relationship("Invoice", back_populates="case")
    assigned_to: Mapped[Optional["User"]] = relationship("User", foreign_keys=[assigned_to_user_id])
    promises: Mapped[list["PromiseToPay"]] = relationship(
        "PromiseToPay", back_populates="case", cascade="all, delete-orphan"
    )
    recovery_actions: Mapped[list["RecoveryAction"]] = relationship(
        "RecoveryAction", back_populates="case", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "case_number", name="uq_case_org_number"),
    )
