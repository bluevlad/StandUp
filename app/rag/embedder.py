"""
nomic-embed-text 임베딩 — Ollama 호출.

성능 노트:
- nomic-embed-text 출력 차원: 768
- /api/embeddings 는 단건만 받으므로 청크 별로 호출 (Ollama 자체 캐시 활용)
- 호출 실패 시 NULL 로 남기고 재시도 가능 — embedding IS NULL 인 청크만 다음 패스에서 처리
"""

from __future__ import annotations

import logging
from typing import Iterable

import httpx
from sqlalchemy import select, update

from ..core.config import settings
from ..core.database import SessionLocal
from ..models.insight import NewsletterChunk

logger = logging.getLogger(__name__)


def _embed_one(client: httpx.Client, text: str) -> list[float] | None:
    try:
        r = client.post(
            f"{settings.ollama_base_url}/api/embeddings",
            json={"model": settings.ollama_model_embed, "prompt": text},
            timeout=settings.ollama_timeout_sec,
        )
        r.raise_for_status()
        data = r.json()
        emb = data.get("embedding")
        if not isinstance(emb, list) or not emb:
            return None
        return emb
    except Exception as e:  # noqa: BLE001
        logger.warning("embed 실패 (%s): %s", text[:60], e)
        return None


def embed_texts(texts: Iterable[str]) -> list[list[float] | None]:
    out: list[list[float] | None] = []
    with httpx.Client(trust_env=False) as client:
        for t in texts:
            out.append(_embed_one(client, t))
    return out


def embed_pending_chunks(batch_size: int = 64) -> int:
    """embedding IS NULL 인 청크만 골라 임베딩 채움."""
    embedded = 0
    while True:
        with SessionLocal() as session:
            stmt = (
                select(NewsletterChunk)
                .where(NewsletterChunk.embedding.is_(None))
                .limit(batch_size)
            )
            chunks: list[NewsletterChunk] = list(session.scalars(stmt))
            if not chunks:
                break

            with httpx.Client(trust_env=False) as client:
                for ch in chunks:
                    emb = _embed_one(client, ch.chunk_text[:8000])
                    if emb is None:
                        continue
                    ch.embedding = emb
                    embedded += 1
            session.commit()

        if len(chunks) < batch_size:
            break
    return embedded
