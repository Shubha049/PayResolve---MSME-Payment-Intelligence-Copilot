"""
Stubs for models to be expanded in Phase 3 through Phase 6:
- Contract (Phase 2 extraction links to it)
- Payment
- RiskAssessment
- Conversation
- GeneratedDocument

NOTE: Document model has been fully implemented in app.models.document
"""
from typing import Optional
from sqlalchemy import String, Text, ForeignKey, JSON, Numeric, Date
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Contract(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "contracts"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    contract_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    terms_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)




class Payment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "payments"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    payment_date: Mapped[str] = mapped_column(Date, nullable=False)
    reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)


class RiskAssessment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    One row per scoring event — history is preserved, never overwritten.
    scoring_method: "heuristic" | "ml"
    model_version:  "heuristic" | "synthetic_v1" | "real_vN"
    top_factors:    [{name, contribution, label}, ...] — same format for both modes.
    """
    __tablename__ = "risk_assessments"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Invoice being scored (primary target)
    invoice_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Customer-level aggregate score (nullable — set when scoring customer aggregate)
    customer_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("customers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Linked case (optional — set when scoring triggers from a case event)
    case_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Score: 0.0 (lowest risk) → 1.0 (highest risk)
    risk_score: Mapped[float] = mapped_column(nullable=False)
    # Derived category: "Low" | "Medium" | "High"
    risk_category: Mapped[str] = mapped_column(String(20), nullable=False)
    # Top 3–5 contributing factors; same JSON structure for heuristic and ML modes
    # [{name: str, contribution: float, label: str}, ...]
    top_factors: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # Identifies the model artifact used: "heuristic", "synthetic_v1", "real_vN"
    model_version: Mapped[str] = mapped_column(String(50), nullable=False, default="heuristic")
    # "heuristic" or "ml" — frontend uses this to show provisional badge
    scoring_method: Mapped[str] = mapped_column(String(20), nullable=False, default="heuristic")


class Conversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "conversations"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), default="Copilot Chat")
    messages: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class GeneratedDocument(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "generated_documents"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="SET NULL"), nullable=True
    )
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)  # REMINDER, DISPUTE_SUMMARY, etc.
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
