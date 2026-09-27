from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.invoice import Invoice
    from app.models.case import Case


class Customer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "customers"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tax_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # GSTIN/PAN/EIN
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization", back_populates="customers")
    invoices: Mapped[List["Invoice"]] = relationship(
        "Invoice", back_populates="customer", cascade="all, delete-orphan"
    )
    cases: Mapped[List["Case"]] = relationship(
        "Case", back_populates="customer", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_customer_org_name"),
    )
