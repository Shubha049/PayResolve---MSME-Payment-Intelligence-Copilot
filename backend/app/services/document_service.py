"""
Document processing service for PayResolve AI Phase 2.

Responsibilities:
  1. File validation (type allowlist, size cap, path traversal protection)
  2. Text extraction:  PDF → PyMuPDF, DOCX → python-docx, images → Tesseract OCR,
                       XLSX/CSV → openpyxl/csv
  3. Document classification (heuristic keyword scoring)
  4. Structured field extraction WITH EVIDENCE
       Every returned field is: {value, page, source_text, confidence, status}
       status ∈ ["verified", "inferred", "missing"]
  5. Chunking for RAG  (512-char chunks with 64-char overlap, page-aware)

DESIGN CONSTRAINT: This service NEVER fabricates values. If a field cannot be
found with reasonable confidence it is marked status="missing" with value=null.
"""

import io
import os
import re
import uuid
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "uploads"))

ALLOWED_MIME_TYPES: set[str] = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "image/png",
    "image/jpeg",
    "image/tiff",
    "text/csv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

ALLOWED_EXTENSIONS: set[str] = {".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".csv", ".xlsx", ".xls"}

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class DocumentValidationError(ValueError):
    """Raised for any upload validation failure."""


def validate_upload(filename: str, content_type: str, file_bytes: bytes) -> None:
    """
    Validate uploaded file for type, size, and path traversal.
    Raises DocumentValidationError on any issue.
    """
    # Path traversal protection
    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename or "/" in filename or "\\" in filename:
        raise DocumentValidationError("Invalid filename — possible path traversal attempt.")

    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise DocumentValidationError(
            f"File type '{ext}' is not allowed. "
            f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # Content type is client-supplied, but must still agree with the extension allowlist.
    if content_type not in ALLOWED_MIME_TYPES:
        raise DocumentValidationError("The supplied file content type is not allowed.")

    if len(file_bytes) > MAX_FILE_SIZE:
        mb = len(file_bytes) / (1024 * 1024)
        raise DocumentValidationError(f"File too large ({mb:.1f} MB). Maximum is 20 MB.")

    if len(file_bytes) == 0:
        raise DocumentValidationError("Empty file uploaded.")


def save_upload(file_bytes: bytes, original_name: str, org_id: str) -> tuple[str, Path]:
    """
    Save uploaded bytes to disk with a UUID-based filename.
    Returns (stored_filename, full_path).
    """
    ext = Path(original_name).suffix.lower()
    stored_name = f"{uuid.uuid4().hex}{ext}"
    org_dir = UPLOAD_DIR / org_id
    org_dir.mkdir(parents=True, exist_ok=True)
    full_path = org_dir / stored_name
    full_path.write_bytes(file_bytes)
    return stored_name, full_path


# ---------------------------------------------------------------------------
# Text Extraction
# ---------------------------------------------------------------------------

def extract_text_from_bytes(file_bytes: bytes, filename: str) -> tuple[str, int]:
    """
    Extract plain text from a file. Returns (text, page_count).
    page_count is 1 for flat text formats.
    """
    ext = Path(filename).suffix.lower()
    try:
        if ext == ".pdf":
            return _extract_pdf(file_bytes)
        elif ext in {".docx", ".doc"}:
            return _extract_docx(file_bytes)
        elif ext in {".png", ".jpg", ".jpeg", ".tiff", ".tif"}:
            return _extract_image(file_bytes), 1
        elif ext == ".csv":
            return _extract_csv(file_bytes), 1
        elif ext in {".xlsx", ".xls"}:
            return _extract_xlsx(file_bytes)
        else:
            return "", 0
    except Exception as exc:
        logger.warning("Text extraction failed for %s: %s", filename, exc)
        return "", 0


def _extract_pdf(file_bytes: bytes) -> tuple[str, int]:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pages_text = []
        for page in doc:
            pages_text.append(page.get_text())
        doc.close()
        return "\n\n".join(pages_text), len(pages_text)
    except ImportError:
        logger.warning("PyMuPDF not installed — PDF extraction skipped.")
        return "", 0


def _extract_docx(file_bytes: bytes) -> tuple[str, int]:
    try:
        from docx import Document as DocxDocument
        doc = DocxDocument(io.BytesIO(file_bytes))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        return text, 1
    except ImportError:
        logger.warning("python-docx not installed — DOCX extraction skipped.")
        return "", 1


def _extract_image(file_bytes: bytes) -> str:
    try:
        from PIL import Image
        import pytesseract
        image = Image.open(io.BytesIO(file_bytes))
        return pytesseract.image_to_string(image)
    except ImportError:
        logger.warning("Pillow/pytesseract not installed — image OCR skipped.")
        return ""
    except Exception as exc:
        logger.warning("OCR failed: %s", exc)
        return ""


def _extract_csv(file_bytes: bytes) -> str:
    import csv
    text = file_bytes.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    return "\n".join(",".join(row) for row in reader)


def _extract_xlsx(file_bytes: bytes) -> tuple[str, int]:
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        rows_text = []
        sheet_count = 0
        for ws in wb.worksheets:
            sheet_count += 1
            for row in ws.iter_rows(values_only=True):
                row_vals = [str(c) for c in row if c is not None]
                if row_vals:
                    rows_text.append("\t".join(row_vals))
        wb.close()
        return "\n".join(rows_text), sheet_count
    except ImportError:
        logger.warning("openpyxl not installed — XLSX extraction skipped.")
        return "", 1


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_CLASSIFICATION_KEYWORDS: dict[str, list[str]] = {
    "INVOICE": [
        "invoice", "invoice no", "invoice number", "bill to", "tax invoice",
        "gst invoice", "payment due", "amount due", "total due",
    ],
    "CONTRACT": [
        "agreement", "contract", "parties", "whereas", "terms and conditions",
        "obligations", "termination", "governing law", "signed by",
    ],
    "PURCHASE_ORDER": [
        "purchase order", "po number", "po #", "order number", "ship to",
        "deliver to", "vendor", "buyer", "quantity", "unit price",
    ],
    "RECEIPT": [
        "receipt", "received from", "payment received", "paid on", "cash receipt",
        "acknowledgement of payment",
    ],
    "CORRESPONDENCE": [
        "dear", "sincerely", "regards", "subject:", "re:", "follow up",
        "reminder", "dispute", "escalation",
    ],
}


def classify_document(text: str) -> tuple[str, float]:
    """
    Classify document type using keyword heuristics.
    Returns (doc_type, confidence 0–1).
    """
    if not text.strip():
        return "UNKNOWN", 0.0

    text_lower = text.lower()
    scores: dict[str, int] = {}
    for doc_type, keywords in _CLASSIFICATION_KEYWORDS.items():
        hit = sum(1 for kw in keywords if kw in text_lower)
        scores[doc_type] = hit

    best_type = max(scores, key=lambda k: scores[k])
    best_score = scores[best_type]
    total_kw = sum(len(v) for v in _CLASSIFICATION_KEYWORDS.values())

    if best_score == 0:
        return "UNKNOWN", 0.0

    confidence = min(best_score / max(total_kw * 0.1, 1), 1.0)
    return best_type, round(confidence, 3)


# ---------------------------------------------------------------------------
# Field Extraction with Evidence
# ---------------------------------------------------------------------------

def _evidence_field(
    value: Any,
    page: Optional[int],
    source_text: str,
    confidence: float,
    status: str = "verified",
) -> dict:
    return {
        "value": value,
        "page": page,
        "source_text": source_text[:300] if source_text else None,
        "confidence": round(confidence, 3),
        "status": status,  # "verified" | "inferred" | "missing"
    }


def _missing_field() -> dict:
    return _evidence_field(None, None, "", 0.0, "missing")


# Regex patterns — deliberately conservative to avoid false positives
_RE_INVOICE_NUMBER = re.compile(
    r"\b(?:invoice\s*(?:no|num|number|#|\.)[:\s]*|invoice\s*[:#]\s*|\binv\s*[:#.-]\s*|\binv\s+no[:\s]*)\s*([A-Z0-9][-A-Z0-9/]{1,30})",
    re.IGNORECASE,
)
_RE_DATE = re.compile(
    r"\b(?:invoice\s*date|date\s*of\s*invoice|issued?(?:\s*on)?)[:\s]+"
    r"(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}|\d{4}[\/\-]\d{2}[\/\-]\d{2})",
    re.IGNORECASE,
)
_RE_DUE_DATE = re.compile(
    r"\b(?:due\s*(?:date|on|by)|payment\s*due(?:\s*date)?)[:\s]+"
    r"(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}|\d{4}[\/\-]\d{2}[\/\-]\d{2})",
    re.IGNORECASE,
)
_RE_TOTAL = re.compile(
    r"\b(?:total\s*(?:amount|due|payable|invoice\s*amount)|amount\s*due|grand\s*total)[:\s]*"
    r"(?:USD|INR|EUR|GBP|₹|\$|€|£)?\s*([\d,]+(?:\.\d{1,2})?)",
    re.IGNORECASE,
)
_RE_VENDOR = re.compile(
    r"\b(?:from|vendor|supplier|billed?\s*by|invoice\s*from|seller)[:\s]+([A-Za-z0-9 .&,'-]{3,80})",
    re.IGNORECASE,
)
_RE_BUYER = re.compile(
    r"\b(?:bill\s*to|billed\s*to|sold\s*to|ship\s*to|customer|client)[:\s]+([A-Za-z0-9 .&,'-]{3,80})",
    re.IGNORECASE,
)


def _find_in_pages(pages: list[str], pattern: re.Pattern) -> tuple[Optional[re.Match], Optional[int]]:
    """Search pattern across all pages, return (match, 1-indexed page number)."""
    for i, page_text in enumerate(pages):
        m = pattern.search(page_text)
        if m:
            return m, i + 1
    return None, None


def extract_fields_with_evidence(text: str, page_count: int = 1) -> dict[str, dict]:
    """
    Extract structured fields from document text with full evidence tracking.
    Each field: {value, page, source_text, confidence, status}

    POLICY: Only mark "verified" if we have a regex match. Never guess.
    """
    # Split text into per-page segments (heuristic: double-newline separation)
    if page_count > 1:
        # PyMuPDF separates pages with form-feed or double-newline
        segments = re.split(r"\n{3,}|\f", text)
        pages = segments if len(segments) == page_count else [text]
    else:
        pages = [text]

    fields: dict[str, dict] = {}

    # Invoice number
    m, pg = _find_in_pages(pages, _RE_INVOICE_NUMBER)
    if m:
        fields["invoice_number"] = _evidence_field(m.group(1).strip(), pg, m.group(0), 0.85)
    else:
        fields["invoice_number"] = _missing_field()

    # Invoice date
    m, pg = _find_in_pages(pages, _RE_DATE)
    if m:
        fields["invoice_date"] = _evidence_field(m.group(1).strip(), pg, m.group(0), 0.85)
    else:
        fields["invoice_date"] = _missing_field()

    # Due date
    m, pg = _find_in_pages(pages, _RE_DUE_DATE)
    if m:
        fields["due_date"] = _evidence_field(m.group(1).strip(), pg, m.group(0), 0.85)
    else:
        fields["due_date"] = _missing_field()

    # Total amount
    m, pg = _find_in_pages(pages, _RE_TOTAL)
    if m:
        raw_amount = m.group(1).replace(",", "")
        try:
            amount = float(raw_amount)
            fields["total_amount"] = _evidence_field(amount, pg, m.group(0), 0.80)
        except ValueError:
            fields["total_amount"] = _missing_field()
    else:
        fields["total_amount"] = _missing_field()

    # Vendor / issuer
    m, pg = _find_in_pages(pages, _RE_VENDOR)
    if m:
        fields["vendor"] = _evidence_field(m.group(1).strip(), pg, m.group(0), 0.70, "inferred")
    else:
        fields["vendor"] = _missing_field()

    # Buyer / recipient
    m, pg = _find_in_pages(pages, _RE_BUYER)
    if m:
        fields["buyer"] = _evidence_field(m.group(1).strip(), pg, m.group(0), 0.70, "inferred")
    else:
        fields["buyer"] = _missing_field()

    return fields


# ---------------------------------------------------------------------------
# Chunking for RAG (Phase 3 prep)
# ---------------------------------------------------------------------------

CHUNK_SIZE    = 512   # characters
CHUNK_OVERLAP = 64


def chunk_text(text: str, page_count: int = 1) -> list[dict]:
    """
    Split text into overlapping chunks for embedding.
    Each chunk: {chunk_index, chunk_text, page_number, char_start, char_end}
    """
    if not text.strip():
        return []

    chunks = []
    # Split text into per-page segments
    if page_count > 1:
        segments = re.split(r"\n{3,}|\f", text)
        pages = segments if len(segments) == page_count else [text] * page_count
    else:
        pages = [text]

    global_char = 0
    chunk_index = 0

    for page_idx, page_text in enumerate(pages, start=1):
        page_len = len(page_text)
        start = 0
        while start < page_len:
            end = start + CHUNK_SIZE
            chunk = page_text[start:end]
            if chunk.strip():
                chunks.append({
                    "chunk_index": chunk_index,
                    "chunk_text":  chunk,
                    "page_number": page_idx,
                    "char_start":  global_char + start,
                    "char_end":    global_char + min(end, page_len),
                })
                chunk_index += 1
            start += CHUNK_SIZE - CHUNK_OVERLAP
        global_char += page_len

    return chunks


# ---------------------------------------------------------------------------
# Full processing pipeline (called from background task)
# ---------------------------------------------------------------------------

async def process_document(
    db,
    document_id: str,
    org_id: str,
    file_bytes: bytes,
    filename: str,
) -> None:
    """
    Full async processing pipeline:
      1. Extract text
      2. Classify document
      3. Extract structured fields with evidence
      4. Chunk text (stored for Phase 3 RAG embedding)
      5. Update Document record in DB

    On any exception: mark document as FAILED with error_message.
    """
    from sqlalchemy import select
    from app.models.document import Document, DocumentChunk, DocStatus

    # Mark PROCESSING
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        logger.error("Document %s not found for processing", document_id)
        return

    doc.status = DocStatus.PROCESSING
    await db.commit()
    await db.refresh(doc)

    try:
        # 1. Extract text
        text, page_count = extract_text_from_bytes(file_bytes, filename)

        # 2. Classify
        doc_type, confidence = classify_document(text)

        # 3. Extract fields
        extracted_fields = extract_fields_with_evidence(text, page_count)

        # 4. Chunk
        chunks_data = chunk_text(text, page_count)

        # 5. Persist chunks
        for c in chunks_data:
            chunk = DocumentChunk(
                organization_id=org_id,
                document_id=document_id,
                chunk_index=c["chunk_index"],
                chunk_text=c["chunk_text"],
                page_number=c["page_number"],
                char_start=c["char_start"],
                char_end=c["char_end"],
            )
            db.add(chunk)

        # 6. Update document
        doc.extracted_text            = text or None
        doc.page_count                = page_count or None
        doc.doc_type                  = doc_type
        doc.classification_confidence = confidence
        doc.extracted_fields          = extracted_fields
        doc.status                    = DocStatus.DONE

        await db.commit()
        logger.info("Document %s processed successfully: type=%s, pages=%d, chunks=%d",
                    document_id, doc_type, page_count, len(chunks_data))

        # 7. Embed & index into Qdrant Vector Store
        await index_document_chunks(db, document_id, org_id)

    except Exception as exc:
        logger.exception("Document %s processing failed", document_id)
        doc.status        = DocStatus.FAILED
        doc.error_message = str(exc)[:500]
        await db.commit()


async def index_document_chunks(db, document_id: str, org_id: str) -> int:
    """
    Generate embeddings for all unindexed chunks of a document and upsert into Qdrant.
    Returns count of points indexed.
    """
    from sqlalchemy import select
    from app.models.document import Document, DocumentChunk
    from app.services.embedding_service import get_embedding_provider
    from app.services.vector_store import upsert_chunks

    doc_res = await db.execute(select(Document).where(Document.id == document_id, Document.organization_id == org_id))
    doc = doc_res.scalar_one_or_none()
    if not doc:
        return 0

    chunks_res = await db.execute(
        select(DocumentChunk).where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.organization_id == org_id,
        ).order_by(DocumentChunk.chunk_index)
    )
    chunks = chunks_res.scalars().all()
    if not chunks:
        return 0

    texts = [chk.chunk_text for chk in chunks]
    embedder = get_embedding_provider()
    vectors = embedder.embed_texts(texts)

    payloads = [
        {
            "chunk_id":      chk.id,
            "organization_id": org_id,
            "document_id":   document_id,
            "chunk_index":   chk.chunk_index,
            "invoice_id":    doc.invoice_id,
            "case_id":       doc.case_id,
            "page_number":   chk.page_number or 1,
            "doc_type":      doc.doc_type,
            "document_name": doc.original_name,
            "chunk_text":    chk.chunk_text,
        }
        for chk in chunks
    ]

    point_ids = upsert_chunks(payloads, vectors)
    for chk, pid in zip(chunks, point_ids):
        chk.embedding_id = str(pid)

    await db.commit()
    logger.info("Successfully indexed %d chunks for doc %s into Qdrant", len(point_ids), document_id)
    return len(point_ids)
