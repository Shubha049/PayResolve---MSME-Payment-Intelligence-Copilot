"""
Documents API schemas for Phase 2.
All extracted fields carry evidence; no fabrication.
"""
from typing import Optional
from pydantic import BaseModel


class EvidenceField(BaseModel):
    """A single extracted field with provenance."""
    value:       Optional[str | float | int]
    page:        Optional[int]
    source_text: Optional[str]
    confidence:  float
    status:      str  # "verified" | "inferred" | "missing"


class DocumentRead(BaseModel):
    id:                       str
    organization_id:          str
    original_name:            str
    file_name:                str
    file_size:                int
    mime_type:                str
    doc_type:                 str
    status:                   str
    classification_confidence: Optional[float]
    page_count:               Optional[int]
    extracted_fields:         Optional[dict[str, EvidenceField]]
    error_message:            Optional[str]
    invoice_id:               Optional[str]
    case_id:                  Optional[str]
    created_at:               str

    model_config = {"from_attributes": True}


class DocumentListItem(BaseModel):
    id:            str
    original_name: str
    doc_type:      str
    status:        str
    file_size:     int
    page_count:    Optional[int]
    created_at:    str

    model_config = {"from_attributes": True}


class DocumentChunkRead(BaseModel):
    id:          str
    chunk_index: int
    chunk_text:  str
    page_number: Optional[int]
    char_start:  Optional[int]
    char_end:    Optional[int]

    model_config = {"from_attributes": True}
