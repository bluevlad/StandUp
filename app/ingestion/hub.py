"""
Ingestion Hub.

connector 들을 순회하며 fetch → canonical → DB upsert (멱등) → RAG 청크 색인.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.database import SessionLocal
from ..models.insight import IngestionEvent, NewsletterChunk
from .connectors import build_connectors
from .schemas import CanonicalEvent, FetchResult

logger = logging.getLogger(__name__)


@dataclass
class HubResult:
    fetched: int
    new_events: int
    new_chunks: int
    per_connector: dict[str, dict]
    errors: list[str]


class IngestionHub:
    """모든 connector 를 순회 실행하고 정규화 이벤트를 영속."""

    def __init__(self, embed_chunks: bool = True):
        self.embed_chunks = embed_chunks

    def run(self, since: datetime | None = None, until: datetime | None = None) -> HubResult:
        until = until or datetime.now(timezone.utc)
        since = since or (until - timedelta(days=settings.insight_window_days))

        connectors = build_connectors()
        if not connectors:
            logger.warning("활성 connector 없음")
            return HubResult(0, 0, 0, {}, ["no connectors"])

        all_results: list[FetchResult] = []
        for c in connectors:
            logger.info("ingestion: %s 시작 (since=%s)", c.name, since.isoformat())
            res = c.fetch_safe(since, until)
            logger.info(
                "ingestion: %s 완료 events=%d ok=%s",
                c.name, len(res.events), res.ok,
            )
            all_results.append(res)

        # 영속 + 임베딩
        new_events = 0
        new_chunks = 0
        per_conn: dict[str, dict] = {}
        errors: list[str] = []

        with SessionLocal() as session:
            for res in all_results:
                ce = self._persist(session, res.events)
                per_conn[res.connector_name] = {
                    "fetched": len(res.events),
                    "new_events": ce[0],
                    "new_chunks": ce[1],
                    "ok": res.ok,
                    "error": res.error,
                }
                new_events += ce[0]
                new_chunks += ce[1]
                if res.error:
                    errors.append(f"{res.connector_name}: {res.error}")
            session.commit()

        # 임베딩은 별도 패스 — DB 트랜잭션 분리 (Ollama 장애가 ingestion 데이터 손실로 이어지지 않도록)
        if self.embed_chunks and new_chunks > 0:
            try:
                from ..rag.embedder import embed_pending_chunks
                embedded = embed_pending_chunks()
                logger.info("RAG 임베딩 완료: %d", embedded)
            except Exception as e:  # noqa: BLE001
                logger.error("RAG 임베딩 실패: %s", e, exc_info=True)
                errors.append(f"embed: {e}")

        total_fetched = sum(len(r.events) for r in all_results)
        return HubResult(
            fetched=total_fetched, new_events=new_events, new_chunks=new_chunks,
            per_connector=per_conn, errors=errors,
        )

    def _persist(self, session: Session, events: Iterable[CanonicalEvent]) -> tuple[int, int]:
        new_events = 0
        new_chunks = 0
        for ev in events:
            content_hash = ev.compute_hash()
            stmt = pg_insert(IngestionEvent).values(
                source_type=ev.source_type,
                source_id=ev.source_id,
                source_url=ev.source_url,
                occurred_at=ev.occurred_at,
                service_tag=ev.service_tag,
                severity=ev.severity,
                category=ev.category,
                title=ev.title,
                content_hash=content_hash,
                canonical=ev.canonical,
                raw_excerpt=ev.raw_excerpt,
            ).on_conflict_do_nothing(
                constraint="uq_ingest_source_dedup",
            ).returning(IngestionEvent.id)

            row = session.execute(stmt).fetchone()
            if not row:
                # 이미 존재 — 스킵
                continue

            event_id = row[0]
            new_events += 1

            # 청크 색인
            for chunk_spec in ev.extra_chunks:
                session.add(NewsletterChunk(
                    collection=chunk_spec.collection,
                    event_id=event_id,
                    chunk_text=chunk_spec.text,
                    metadata_json=chunk_spec.metadata or {},
                ))
                new_chunks += 1

        return new_events, new_chunks
