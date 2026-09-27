"""
Qdrant Vector Store service for PayResolve AI.

CRITICAL SECURITY CONSTRAINT:
  All searches and deletions enforce `organization_id` as a hard filter
  at the Qdrant query level (must clause). Post-filtering at application layer
  is strictly prohibited to guarantee tenant isolation.
"""

import logging
from typing import Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.config import settings

logger = logging.getLogger(__name__)

_qdrant_client: Optional[QdrantClient] = None


def get_qdrant_client() -> QdrantClient:
    """
    Get or initialize the Qdrant client singleton.
    Connects to external Qdrant if QDRANT_URL is set, otherwise runs in-memory/embedded.
    """
    global _qdrant_client
    if _qdrant_client is None:
        if settings.QDRANT_URL:
            logger.info("Connecting to Qdrant server at %s", settings.QDRANT_URL)
            _qdrant_client = QdrantClient(url=settings.QDRANT_URL)
        elif settings.QDRANT_PATH and settings.QDRANT_PATH != ":memory:":
            logger.info("Initializing Qdrant with local disk storage at %s", settings.QDRANT_PATH)
            _qdrant_client = QdrantClient(path=settings.QDRANT_PATH)
        else:
            logger.info("Initializing Qdrant in-memory mode")
            _qdrant_client = QdrantClient(location=":memory:")

        # Ensure collection exists on first init
        init_collection(_qdrant_client)

    return _qdrant_client


def set_qdrant_client(client: QdrantClient) -> None:
    """Explicitly set Qdrant client instance (useful in tests)."""
    global _qdrant_client
    _qdrant_client = client
    init_collection(_qdrant_client)


def init_collection(client: QdrantClient, dimension: int = 384) -> None:
    """
    Ensure the Qdrant collection exists and payload indexes are created.
    """
    collection_name = settings.QDRANT_COLLECTION
    try:
        collections = client.get_collections().collections
        exists = any(c.name == collection_name for c in collections)
        if not exists:
            logger.info("Creating Qdrant collection '%s' with dim=%d", collection_name, dimension)
            client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=dimension,
                    distance=models.Distance.COSINE,
                ),
            )
            # Create payload index on organization_id for fast & secure tenant filtering
            if settings.QDRANT_URL:
                client.create_payload_index(
                    collection_name=collection_name,
                    field_name="organization_id",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
                client.create_payload_index(
                    collection_name=collection_name,
                    field_name="document_id",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
    except Exception as exc:
        logger.warning("Could not initialize Qdrant collection '%s': %s", collection_name, exc)


def upsert_chunks(
    chunks: list[dict[str, Any]],
    vectors: list[list[float]],
) -> list[str]:
    """
    Upsert document chunks and their embedding vectors into Qdrant.
    Returns list of point IDs.
    """
    if not chunks or not vectors:
        return []

    client = get_qdrant_client()
    collection_name = settings.QDRANT_COLLECTION
    points: list[models.PointStruct] = []
    point_ids: list[str] = []

    for chunk, vector in zip(chunks, vectors):
        point_id = chunk["chunk_id"]
        point_ids.append(point_id)
        points.append(
            models.PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "organization_id": chunk["organization_id"],
                    "document_id":    chunk["document_id"],
                    "chunk_id":       chunk["chunk_id"],
                    "chunk_index":    chunk.get("chunk_index", 0),
                    "invoice_id":     chunk.get("invoice_id"),
                    "case_id":        chunk.get("case_id"),
                    "page_number":    chunk.get("page_number", 1),
                    "doc_type":       chunk.get("doc_type", "UNKNOWN"),
                    "document_name":  chunk.get("document_name", ""),
                    "chunk_text":     chunk.get("chunk_text", ""),
                },
            )
        )

    client.upsert(collection_name=collection_name, points=points)
    return point_ids


def search_chunks(
    org_id: str,
    query_vector: list[float],
    limit: int = 5,
    score_threshold: Optional[float] = None,
    doc_type: Optional[str] = None,
    invoice_id: Optional[str] = None,
    case_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Search vector collection for the given organization.
    
    SECURITY:
      organization_id is an obligatory 'must' filter at the Qdrant level.
      Cross-tenant retrieval is strictly impossible.
    """
    client = get_qdrant_client()
    collection_name = settings.QDRANT_COLLECTION

    # Build hard-filtered must conditions
    must_conditions: list[models.Condition] = [
        models.FieldCondition(
            key="organization_id",
            match=models.MatchValue(value=org_id),
        )
    ]

    if doc_type:
        must_conditions.append(
            models.FieldCondition(
                key="doc_type",
                match=models.MatchValue(value=doc_type.upper()),
            )
        )
    if invoice_id:
        must_conditions.append(
            models.FieldCondition(
                key="invoice_id",
                match=models.MatchValue(value=invoice_id),
            )
        )
    if case_id:
        must_conditions.append(
            models.FieldCondition(
                key="case_id",
                match=models.MatchValue(value=case_id),
            )
        )

    qdrant_filter = models.Filter(must=must_conditions)

    # Perform search using client.query_points
    response = client.query_points(
        collection_name=collection_name,
        query=query_vector,
        query_filter=qdrant_filter,
        limit=limit,
        score_threshold=score_threshold,
    )

    results = []
    for hit in response.points:
        payload = hit.payload or {}
        results.append({
            "point_id":      hit.id,
            "score":         round(hit.score, 4),
            "chunk_id":      payload.get("chunk_id"),
            "document_id":   payload.get("document_id"),
            "document_name": payload.get("document_name", ""),
            "page_number":   payload.get("page_number", 1),
            "doc_type":      payload.get("doc_type", "UNKNOWN"),
            "chunk_text":    payload.get("chunk_text", ""),
            "invoice_id":    payload.get("invoice_id"),
            "case_id":       payload.get("case_id"),
        })

    return results


def delete_document_points(org_id: str, document_id: str) -> None:
    """
    Delete all vector points belonging to a specific document under an org.
    Prevents orphaned points when documents are deleted or re-processed.
    """
    client = get_qdrant_client()
    collection_name = settings.QDRANT_COLLECTION

    delete_filter = models.Filter(
        must=[
            models.FieldCondition(
                key="organization_id",
                match=models.MatchValue(value=org_id),
            ),
            models.FieldCondition(
                key="document_id",
                match=models.MatchValue(value=document_id),
            ),
        ]
    )
    client.delete(collection_name=collection_name, points_selector=delete_filter)


def count_points_by_org(org_id: str) -> int:
    """Count total vector points indexed for an organization."""
    client = get_qdrant_client()
    collection_name = settings.QDRANT_COLLECTION

    org_filter = models.Filter(
        must=[
            models.FieldCondition(
                key="organization_id",
                match=models.MatchValue(value=org_id),
            )
        ]
    )
    res = client.count(collection_name=collection_name, count_filter=org_filter)
    return res.count
