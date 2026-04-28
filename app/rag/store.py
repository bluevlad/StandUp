"""
RAG store helpers — 발송된 뉴스레터 본문을 corpus_newsletters 로 색인.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from ..models.insight import COLLECTION_NEWSLETTERS, Newsletter, NewsletterChunk
from .embedder import embed_texts

logger = logging.getLogger(__name__)


def index_newsletter(session: Session, nl: Newsletter, chunk_size: int = 1500) -> int:
    """뉴스레터 본문을 청크로 분할 색인 — 다음 발송 시 RAG 가 과거 사례 참고."""
    text = (nl.plain_summary or "") + "\n\n" + (nl.html_body or "")
    if not text.strip():
        return 0

    chunks: list[str] = []
    cur = 0
    while cur < len(text):
        chunks.append(text[cur:cur + chunk_size])
        cur += chunk_size

    embs = embed_texts(chunks)
    inserted = 0
    for c, emb in zip(chunks, embs):
        if emb is None:
            continue
        nc = NewsletterChunk(
            collection=COLLECTION_NEWSLETTERS,
            newsletter_id=nl.id,
            chunk_text=c,
            metadata_json={
                "period_start": nl.period_start.isoformat(),
                "period_end": nl.period_end.isoformat(),
                "headline": nl.headline,
            },
        )
        nc.embedding = emb
        session.add(nc)
        inserted += 1
    return inserted
