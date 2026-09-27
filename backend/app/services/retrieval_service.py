"""
Semantic Retrieval and Context Selection Service for PayResolve AI.

Handles:
  1. Query embedding
  2. Qdrant semantic search with hard tenant isolation (organization_id)
  3. Hybrid scoring / reranking (similarity + token overlap + document proximity)
  4. Context window optimization (capped at top-k high-relevance chunks)
"""

import re
import logging
from typing import Any, Optional

from app.services.embedding_service import get_embedding_provider
from app.services.vector_store import search_chunks

logger = logging.getLogger(__name__)


def retrieve_context(
    org_id: str,
    query: str,
    top_k: int = 5,
    score_threshold: Optional[float] = None,
    doc_type: Optional[str] = None,
    invoice_id: Optional[str] = None,
    case_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Retrieve and rerank relevant document chunks for an organization.
    
    SECURITY:
      Enforces tenant isolation by passing org_id into vector search must-clause.
    """
    if not query.strip():
        return []

    # 1. Embed query
    embedder = get_embedding_provider()
    query_vector = embedder.embed_query(query)

    # 2. Fetch candidate chunks from Qdrant (fetch up to 2x top_k for reranking)
    fetch_limit = min(top_k * 2, 20)
    raw_hits = search_chunks(
        org_id=org_id,
        query_vector=query_vector,
        limit=fetch_limit,
        score_threshold=score_threshold,
        doc_type=doc_type,
        invoice_id=invoice_id,
        case_id=case_id,
    )

    if not raw_hits:
        return []

    # 3. Rerank / Context Selection
    # Combine vector cosine similarity with token overlap heuristic
    query_words = set(re.findall(r"\w+", query.lower()))
    reranked = []

    for hit in raw_hits:
        chunk_text = hit["chunk_text"]
        chunk_words = set(re.findall(r"\w+", chunk_text.lower()))
        
        # Keyword overlap bonus
        overlap_count = len(query_words.intersection(chunk_words))
        overlap_boost = min(overlap_count * 0.05, 0.20)

        # Composite score
        final_score = hit["score"] + overlap_boost
        hit["rerank_score"] = round(final_score, 4)
        reranked.append(hit)

    # Sort descending by composite score
    reranked.sort(key=lambda x: x["rerank_score"], reverse=True)

    # Return top_k chunks
    return reranked[:top_k]
