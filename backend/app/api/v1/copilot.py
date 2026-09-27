"""
Copilot and RAG Vector Retrieval API Router for PayResolve AI.

Endpoints:
  POST /copilot/query    — Grounded conversational question-answering with citations
  POST /copilot/search   — Semantic vector search returning ranked passages
  POST /copilot/backfill — Index existing document chunks into Qdrant vector store
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.api.deps import get_current_user, get_current_org_id, get_current_tenant, TenantContext
from app.models.user import User
from app.models.document import Document, DocumentChunk
from app.schemas.copilot import (
    CopilotQueryRequest, CopilotQueryResponse,
    SemanticSearchRequest, SemanticSearchResultItem,
    BackfillResponse,
    RecoveryCopilotQueryResponse,
)
from app.services.copilot_service import answer_copilot_query
from app.services.retrieval_service import retrieve_context
from app.services.document_service import index_document_chunks
from app.services.vector_store import count_points_by_org
from app.services.audit_service import log_audit_event
from app.services.recovery_copilot_service import answer_recovery_question
from app.services.rate_limit import check_copilot_rate_limit

router = APIRouter(prefix="/copilot", tags=["Copilot & RAG"])
logger = logging.getLogger(__name__)


@router.post(
    "/query",
    response_model=CopilotQueryResponse,
    summary="Ask Copilot a question grounded in organization documents",
    description=(
        "Answers user questions using only the organization's verified uploaded documents. "
        "Every response is fenced against prompt injection, includes page-level citations, "
        "and explicitly marks information as [VERIFIED], [INFERRED], or [MISSING]."
    ),
    dependencies=[Depends(check_copilot_rate_limit)],
)
async def query_copilot(
    payload: CopilotQueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_id: str = Depends(get_current_org_id),
):
    try:
        result = await answer_copilot_query(
            org_id=org_id,
            query=payload.query,
            doc_type=payload.doc_type,
            invoice_id=payload.invoice_id,
            case_id=payload.case_id,
        )

        await log_audit_event(
            db,
            organization_id=org_id,
            action="copilot.query",
            entity_type="copilot",
            entity_id=org_id,
            user_id=current_user.id,
            details={
                "query": payload.query[:200],
                "grounded": result["grounded"],
                "citations_count": len(result["citations"]),
            },
        )

        return CopilotQueryResponse(
            answer=result["answer"],
            citations=result["citations"],
            chunks_retrieved=result["chunks_retrieved"],
            grounded=result["grounded"],
        )
    except Exception as exc:
        logger.exception("Copilot query failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to generate a Copilot answer at this time.",
        )


@router.post(
    "/search",
    response_model=list[SemanticSearchResultItem],
    summary="Semantic vector search across organization documents",
    description="Retrieve ranked document chunks matching the query string within the organization.",
    dependencies=[Depends(check_copilot_rate_limit)],
)
async def semantic_search(
    payload: SemanticSearchRequest,
    _: User = Depends(get_current_user),
    org_id: str = Depends(get_current_org_id),
):
    hits = retrieve_context(
        org_id=org_id,
        query=payload.query,
        top_k=payload.limit,
        doc_type=payload.doc_type,
        invoice_id=payload.invoice_id,
        case_id=payload.case_id,
    )

    return [
        SemanticSearchResultItem(
            chunk_id=h.get("chunk_id"),
            document_id=h.get("document_id"),
            document_name=h.get("document_name", "Document"),
            page_number=h.get("page_number", 1),
            doc_type=h.get("doc_type", "UNKNOWN"),
            chunk_text=h.get("chunk_text", ""),
            score=h.get("score", 0.0),
        )
        for h in hits
    ]


@router.post(
    "/backfill",
    response_model=BackfillResponse,
    summary="Embed and backfill all existing document chunks into Qdrant",
    description="Finds any document chunks not yet indexed in Qdrant and embeds them.",
    dependencies=[Depends(check_copilot_rate_limit)],
)
async def backfill_embeddings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_id: str = Depends(get_current_org_id),
):
    # Find all documents belonging to this org
    docs_stmt = select(Document.id).where(Document.organization_id == org_id)
    doc_res = await db.execute(docs_stmt)
    doc_ids = doc_res.scalars().all()

    indexed_docs = 0
    total_chunks = 0

    for doc_id in doc_ids:
        count = await index_document_chunks(db, doc_id, org_id)
        if count > 0:
            indexed_docs += 1
            total_chunks += count

    org_vector_count = count_points_by_org(org_id)

    await log_audit_event(
        db,
        organization_id=org_id,
        action="copilot.backfill",
        entity_type="copilot",
        entity_id=org_id,
        user_id=current_user.id,
        details={"indexed_docs": indexed_docs, "total_chunks": total_chunks},
    )

    return BackfillResponse(
        indexed_documents=indexed_docs,
        indexed_chunks=total_chunks,
        total_org_vectors=org_vector_count,
    )


@router.post(
    "/recovery-query",
    response_model=RecoveryCopilotQueryResponse,
    summary="Ask a question grounded in current recovery records",
)
async def query_recovery_copilot(
    payload: CopilotQueryRequest,
    db: AsyncSession = Depends(get_db),
    tenant: TenantContext = Depends(get_current_tenant),
):
    result = await answer_recovery_question(
        db=db,
        organization_id=tenant.organization_id,
        query=payload.query,
    )
    return RecoveryCopilotQueryResponse(**result)
