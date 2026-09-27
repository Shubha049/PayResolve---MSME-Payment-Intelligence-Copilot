"""
Full Document model with extraction status, evidence-tracked fields, and
classification confidence. Replaces the stub in stubs.py.
"""
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, JSON, Integer, Float, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class DocType(str, PyEnum):
    INVOICE        = "INVOICE"
    CONTRACT       = "CONTRACT"
    PURCHASE_ORDER = "PURCHASE_ORDER"
    RECEIPT        = "RECEIPT"
    CORRESPONDENCE = "CORRESPONDENCE"
    UNKNOWN        = "UNKNOWN"


class DocStatus(str, PyEnum):
    PENDING    = "PENDING"
    PROCESSING = "PROCESSING"
    DONE       = "DONE"
    FAILED     = "FAILED"


class Document(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Represents an uploaded business document. Every extracted field carries
    evidence (page, source_text, confidence) so no fact is fabricated.
    """
    __tablename__ = "documents"

    # Tenant isolation
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # File metadata
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)  # stored name (uuid-based)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False, default="application/octet-stream")

    # Classification
    doc_type: Mapped[str] = mapped_column(
        Enum(DocType, name="doc_type_enum"),
        nullable=False, default=DocType.UNKNOWN,
    )
    classification_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Processing status
    status: Mapped[str] = mapped_column(
        Enum(DocStatus, name="doc_status_enum"),
        nullable=False, default=DocStatus.PENDING,
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Extracted content
    extracted_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    page_count: Mapped[Optional[int]]     = mapped_column(Integer, nullable=True)

    # Evidence-tracked fields: {field_name: {value, page, source_text, confidence, status}}
    # status ∈ ["verified", "inferred", "missing"]
    extracted_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Optional linkage
    invoice_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    case_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="SET NULL"), nullable=True, index=True,
    )

    # Relationships
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan",
    )


class DocumentChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Text chunk for RAG retrieval. Tracks which page the chunk originated from
    so answers can cite "Invoice_102.pdf, page 2".
    """
    __tablename__ = "document_chunks"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text:  Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    char_start:  Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    char_end:    Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Qdrant point ID stored here for fast retrieval in Phase 3
    embedding_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")
