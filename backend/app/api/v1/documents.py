"""
Documents API — Phase 2 Document Intelligence.

Endpoints:
  POST   /documents/upload          — upload + enqueue extraction
  GET    /documents/                — list org documents
  GET    /documents/{id}            — detail with extracted fields + evidence
  DELETE /documents/{id}            — delete record + file
  GET    /documents/{id}/chunks     — list text chunks (RAG debug)
"""
import os
import logging
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter, Depends, HTTPException, UploadFile, File,
    BackgroundTasks, Query, status,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.api.deps import get_current_user, get_current_org_id
from app.models.document import Document, DocumentChunk, DocStatus
from app.models.user import User
from app.schemas.document import DocumentRead, DocumentListItem, DocumentChunkRead
from app.services.document_service import validate_upload, save_upload, process_document
from app.services.audit_service import log_audit_event
from app.services.rate_limit import check_upload_rate_limit

router = APIRouter(prefix="/documents", tags=["Documents"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# POST /documents/upload
# ---------------------------------------------------------------------------

@router.post(
    "/upload",
    response_model=DocumentRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a business document",
    description=(
        "Upload a PDF, DOCX, image, or spreadsheet. The file is validated, "
        "saved, and queued for async extraction. Poll GET /documents/{id} for "
        "status. All extracted fields carry source citations."
    ),
    dependencies=[Depends(check_upload_rate_limit)],
)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    invoice_id: Optional[str] = Query(None, description="Optional: link to an invoice"),
    case_id:    Optional[str] = Query(None, description="Optional: link to a case"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_id: str = Depends(get_current_org_id),
):
    file_bytes = await file.read()

    # Validate
    try:
        validate_upload(
            filename=file.filename or "upload",
            content_type=file.content_type or "application/octet-stream",
            file_bytes=file_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    original_name = file.filename or "upload"
    content_type  = file.content_type or "application/octet-stream"

    # Save to disk
    try:
        stored_name, full_path = save_upload(file_bytes, original_name, org_id)
    except Exception as exc:
        logger.exception("File save failed for organization %s", org_id)
        raise HTTPException(status_code=500, detail="File storage error")

    # Create DB record (PENDING)
    doc = Document(
        organization_id=org_id,
        original_name=original_name,
        file_name=stored_name,
        file_path=str(full_path),
        file_size=len(file_bytes),
        mime_type=content_type,
        invoice_id=invoice_id,
        case_id=case_id,
        status=DocStatus.PENDING,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    await log_audit_event(db, organization_id=org_id, action="document.upload",
                          entity_type="document", entity_id=doc.id,
                          user_id=current_user.id,
                          details={"filename": original_name, "size": len(file_bytes)})

    # Enqueue background extraction (FastAPI BackgroundTasks)
    background_tasks.add_task(
        _run_extraction, doc.id, org_id, file_bytes, original_name
    )

    return _to_read(doc)


async def _run_extraction(document_id: str, org_id: str, file_bytes: bytes, filename: str):
    """Runs in the background — creates its own DB session."""
    from app.database import async_session_factory
    async with async_session_factory() as db:
        try:
            await process_document(db, document_id, org_id, file_bytes, filename)
        except Exception:
            logger.exception("Background extraction task crashed for doc %s", document_id)


# ---------------------------------------------------------------------------
# GET /documents/
# ---------------------------------------------------------------------------

@router.get(
    "/",
    response_model=list[DocumentListItem],
    summary="List documents for the active organisation",
)
async def list_documents(
    doc_type: Optional[str] = Query(None),
    status:   Optional[str] = Query(None),
    limit:    int            = Query(50, le=200),
    offset:   int            = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
    org_id: str = Depends(get_current_org_id),
):
    stmt = select(Document).where(Document.organization_id == org_id)
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type.upper())
    if status:
        stmt = stmt.where(Document.status == status.upper())
    stmt = stmt.order_by(Document.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(stmt)
    docs = result.scalars().all()
    return [_to_list_item(d) for d in docs]


# ---------------------------------------------------------------------------
# GET /documents/{id}
# ---------------------------------------------------------------------------

@router.get(
    "/{document_id}",
    response_model=DocumentRead,
    summary="Get document detail with extracted fields and evidence",
)
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
    org_id: str = Depends(get_current_org_id),
):
    doc = await _get_or_404(db, document_id, org_id)
    return _to_read(doc)


# ---------------------------------------------------------------------------
# DELETE /documents/{id}
# ---------------------------------------------------------------------------

@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_id: str = Depends(get_current_org_id),
):
    doc = await _get_or_404(db, document_id, org_id)
    file_path = Path(doc.file_path)

    await db.delete(doc)
    await db.commit()

    # Clean up vector points from Qdrant
    try:
        from app.services.vector_store import delete_document_points
        delete_document_points(org_id=org_id, document_id=document_id)
    except Exception as exc:
        logger.warning("Could not delete vectors for doc %s: %s", document_id, exc)

    # Best-effort file deletion
    if file_path.exists():
        try:
            file_path.unlink()
        except OSError as exc:
            logger.warning("Could not delete file %s: %s", file_path, exc)

    await log_audit_event(db, organization_id=org_id, action="document.delete",
                          entity_type="document", entity_id=document_id,
                          user_id=current_user.id)


# ---------------------------------------------------------------------------
# GET /documents/{id}/chunks
# ---------------------------------------------------------------------------

@router.get(
    "/{document_id}/chunks",
    response_model=list[DocumentChunkRead],
    summary="List text chunks for a document (RAG debug)",
)
async def list_chunks(
    document_id: str,
    limit:  int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
    org_id: str = Depends(get_current_org_id),
):
    # Confirm ownership first
    await _get_or_404(db, document_id, org_id)

    stmt = (
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_or_404(db: AsyncSession, document_id: str, org_id: str) -> Document:
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.organization_id == org_id,  # tenant isolation enforced here
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _to_read(doc: Document) -> DocumentRead:
    return DocumentRead(
        id=doc.id,
        organization_id=doc.organization_id,
        original_name=doc.original_name,
        file_name=doc.file_name,
        file_size=doc.file_size,
        mime_type=doc.mime_type,
        doc_type=doc.doc_type,
        status=doc.status,
        classification_confidence=doc.classification_confidence,
        page_count=doc.page_count,
        extracted_fields=doc.extracted_fields,
        error_message=doc.error_message,
        invoice_id=doc.invoice_id,
        case_id=doc.case_id,
        created_at=str(doc.created_at),
    )


def _to_list_item(doc: Document) -> DocumentListItem:
    return DocumentListItem(
        id=doc.id,
        original_name=doc.original_name,
        doc_type=doc.doc_type,
        status=doc.status,
        file_size=doc.file_size,
        page_count=doc.page_count,
        created_at=str(doc.created_at),
    )
