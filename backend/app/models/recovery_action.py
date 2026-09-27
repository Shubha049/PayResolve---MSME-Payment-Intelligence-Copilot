"""
RecoveryAction model — tracks operational recovery activities for Cases.

Each action represents a real activity performed during recovery workflow,
such as contacting customer, sending reminders, scheduling follow-ups, etc.
"""
import enum
from datetime import date
from typing import Optional, TYPE_CHECKING
from sqlalchemy import Index, String, Text, ForeignKey, Enum as SQLEnum, Date, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.case import Case
    from app.models.user import User


class RecoveryActionType(str, enum.Enum):
    """
    Recovery action types.
    
    CUSTOMER_CONTACTED: Direct customer contact (phone, in-person, video call)
    EMAIL_SENT: Email communication sent to customer
    REMINDER_SENT: Payment reminder sent (any channel)
    FOLLOW_UP_SCHEDULED: Follow-up activity scheduled
    PAYMENT_DISCUSSED: Discussion with customer about payment
    PROMISE_REQUESTED: Requested payment promise from customer
    EVIDENCE_COLLECTED: Collected evidence/documentation for case
    NOTE_ADDED: Internal note or observation
    STATUS_REVIEWED: Case status review
    """
    CUSTOMER_CONTACTED = "CUSTOMER_CONTACTED"
    EMAIL_SENT = "EMAIL_SENT"
    REMINDER_SENT = "REMINDER_SENT"
    FOLLOW_UP_SCHEDULED = "FOLLOW_UP_SCHEDULED"
    PAYMENT_DISCUSSED = "PAYMENT_DISCUSSED"
    PROMISE_REQUESTED = "PROMISE_REQUESTED"
    PROMISE_OVERDUE = "PROMISE_OVERDUE"
    FOLLOW_UP_DUE = "FOLLOW_UP_DUE"
    BROKEN_PROMISE_ATTENTION = "BROKEN_PROMISE_ATTENTION"
    EVIDENCE_COLLECTED = "EVIDENCE_COLLECTED"
    NOTE_ADDED = "NOTE_ADDED"
    STATUS_REVIEWED = "STATUS_REVIEWED"


class RecoveryAction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Recovery action record for Case workflow.
    
    Tracks operational activities performed during collection/recovery.
    Each action creates corresponding AuditLog entry for timeline.
    """
    __tablename__ = "recovery_actions"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
        doc="Tenant isolation"
    )
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False, index=True,
        doc="Which case this action belongs to"
    )
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        doc="User who performed this action"
    )
    
    action_type: Mapped[RecoveryActionType] = mapped_column(
        SQLEnum(RecoveryActionType), nullable=False, index=True,
        doc="Type of recovery action performed"
    )
    action_date: Mapped[date] = mapped_column(
        Date, nullable=False, index=True,
        doc="When the action was performed"
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        doc="Free-form notes about the action"
    )
    next_follow_up_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True,
        doc="Optional: when to follow up next (if scheduling future action)"
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, doc="Stable source key for automated recovery actions"
    )

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization")
    case: Mapped["Case"] = relationship("Case", back_populates="recovery_actions")
    created_by: Mapped["User"] = relationship("User", foreign_keys=[created_by_user_id])

    __table_args__ = (
        Index(
            "uq_recovery_actions_idempotency_key",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
            postgresql_where=text("idempotency_key IS NOT NULL"),
            mssql_where=text("idempotency_key IS NOT NULL"),
        ),
    )
