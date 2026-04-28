"""
RAG retriever — 컬렉션별 cosine 유사도 검색.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..models.insight import NewsletterChunk, IngestionEvent
from .embedder import embed_texts

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: int
    chunk_text: str
    collection: str
    distance: float
    event_id: Optional[str]
    source_url: Optional[str]
    source_title: Optional[str]
    metadata: dict


def retrieve(
    session: Session,
    query: str,
    collection: str,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    """동일 collection 내 cosine 유사도 top-k."""
    embs = embed_texts([query])
    if not embs or embs[0] is None:
        logger.warning("retrieve: query 임베딩 실패")
        return []
    qvec = embs[0]

    # pgvector 의 cosine distance 연산자 <=> 사용
    sql = text("""
        SELECT
            c.id, c.chunk_text, c.collection, c.metadata_json,
            c.event_id,
            (c.embedding <=> CAST(:qvec AS vector)) AS distance,
            e.source_url, e.title
        FROM newsletter_chunks c
        LEFT JOIN ingestion_events e ON e.id = c.event_id
        WHERE c.collection = :collection
          AND c.embedding IS NOT NULL
        ORDER BY c.embedding <=> CAST(:qvec AS vector)
        LIMIT :k
    """)
    rows = session.execute(sql, {
        "qvec": str(qvec),
        "collection": collection,
        "k": top_k,
    }).mappings().all()

    return [
        RetrievedChunk(
            chunk_id=r["id"],
            chunk_text=r["chunk_text"],
            collection=r["collection"],
            distance=float(r["distance"]),
            event_id=str(r["event_id"]) if r["event_id"] else None,
            source_url=r["source_url"],
            source_title=r["title"],
            metadata=r["metadata_json"] or {},
        )
        for r in rows
    ]
