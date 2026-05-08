"""
Ingestion 정규화 스키마.

각 connector 가 raw 데이터를 CanonicalEvent 로 변환해 hub 에 반환.
hub 가 IngestionEvent 행으로 저장.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class CanonicalEvent:
    """모든 source 가 통일해서 반환하는 정규화 이벤트."""

    source_type: str
    source_id: str                   # source 내 자연키 (issue#, fingerprint, commit sha 등)
    occurred_at: datetime            # tz-aware
    title: str
    canonical: dict[str, Any]        # 구조화된 본문 (jsonb)
    source_url: Optional[str] = None
    service_tag: Optional[str] = None
    severity: Optional[str] = None   # critical|high|medium|low|info
    category: Optional[str] = None   # source 별 자유
    raw_excerpt: Optional[str] = None  # 짧은 미리보기 (UI용)
    extra_chunks: list["ChunkSpec"] = field(default_factory=list)

    def compute_hash(self) -> str:
        """content_hash — canonical 핵심 필드의 sha256."""
        h = hashlib.sha256()
        h.update(self.source_type.encode())
        h.update(b"\x00")
        h.update(self.source_id.encode())
        h.update(b"\x00")
        h.update(self.title.encode())
        h.update(b"\x00")
        # canonical 의 안정적 직렬화
        import json
        h.update(json.dumps(self.canonical, sort_keys=True, ensure_ascii=False).encode())
        return h.hexdigest()


@dataclass
class ChunkSpec:
    """RAG 색인용 청크 사양 — connector 가 권장하는 분할."""

    text: str
    collection: str            # corpus_qa|corpus_logs|corpus_fixes|corpus_tech
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    """connector.fetch() 반환값."""

    events: list[CanonicalEvent]
    connector_name: str
    started_at: datetime
    finished_at: datetime
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None
