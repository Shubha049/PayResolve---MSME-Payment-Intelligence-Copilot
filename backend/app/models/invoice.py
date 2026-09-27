import enum
from datetime import date
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Date, Numeric, Text, ForeignKey, Enum as SQLEnum, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.customer import Customer
    from app.models.case import Case


class InvoiceStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    DISPUTED = "DISPUTED"
    WRITTEN_OFF = "WRITTEN_OFF"


class Invoice(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "invoices"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"), nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        SQLEnum(InvoiceStatus), default=InvoiceStatus.ISSUED, nullable=False, index=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization", back_populates="invoices")
    customer: Mapped["Customer"] = relationship("Customer", back_populates="invoices")
    case: Mapped[Optional["Case"]] = relationship("Case", back_populates="invoice", uselist=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "invoice_number", name="uq_invoice_org_number"),
    )

    @property
    def outstanding_amount(self) -> Decimal:
        return max(Decimal("0.00"), self.total_amount - self.paid_amount)
