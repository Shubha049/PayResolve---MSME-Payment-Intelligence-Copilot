"""
Pydantic schemas for Copilot and RAG vector retrieval.
"""

from typing import Optional, Any
from pydantic import BaseModel, Field


class CopilotQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="User's natural language question")
    doc_type: Optional[str] = Field(None, description="Optional doc type filter e.g. INVOICE, CONTRACT")
    invoice_id: Optional[str] = Field(None, description="Scope query to a specific invoice")
    case_id: Optional[str] = Field(None, description="Scope query to a specific dispute case")
    conversation_id: Optional[str] = Field(None, description="Conversation session ID")


class CitationItem(BaseModel):
    document_id: Optional[str] = None
    document_name: str
    page_number: int
    doc_type: str = "UNKNOWN"
    quote: str


class CopilotQueryResponse(BaseModel):
    answer: str
    citations: list[CitationItem] = []
    chunks_retrieved: int = 0
    grounded: bool = False


class RecoveryCopilotQueryResponse(BaseModel):
    answer: str
    sources: list[dict[str, str]] = []
    grounded: bool = False


class SemanticSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    limit: int = Field(5, ge=1, le=20)
    doc_type: Optional[str] = None
    invoice_id: Optional[str] = None
    case_id: Optional[str] = None


class SemanticSearchResultItem(BaseModel):
    chunk_id: Optional[str] = None
    document_id: Optional[str] = None
    document_name: str
    page_number: int
    doc_type: str
    chunk_text: str
    score: float


class BackfillResponse(BaseModel):
    indexed_documents: int
    indexed_chunks: int
    total_org_vectors: int
