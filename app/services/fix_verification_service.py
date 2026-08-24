"""
Fix 효과 검증 — AGENT_DATA_CONTRACT '자동 효과 검증 로직' 구현.

Auto-Tobe fix 이벤트(journal/commit)에 연결된 LogAnalyzer fingerprint 가
fix 시점 이후 window(기본 7일) 안에 재등장하는지 결정적으로 판정한다.

- verified  ✅ window 경과, 재발 없음
- recurred  ❌ window 내 같은 fingerprint 재등장
- pending   ⏳ window 미경과, 아직 재발 없음
- unlinked  fingerprint 연결 정보 없음 → 검증 불가

판정 결과는 뉴스레터 kpis 에 실려 저장되고, corpus_fixes 청크의
metadata_json 에도 누적되어 retrieval 시 학습 신호로 쓰인다.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.database import SessionLocal
from ..models.insight import (
    COLLECTION_FIXES, IngestionEvent, NewsletterChunk,
    SOURCE_AUTO_TOBE_COMMIT, SOURCE_AUTO_TOBE_JOURNAL, SOURCE_LOGANALYZER,
)

logger = logging.getLogger(__name__)

STATUS_VERIFIED = "verified"
STATUS_RECURRED = "recurred"
STATUS_PENDING = "pending"
STATUS_UNLINKED = "unlinked"

STATUS_LABELS = {
    STATUS_VERIFIED: "✅ 검증됨 (재발 없음)",
    STATUS_RECURRED: "❌ 재발",
    STATUS_PENDING: "⏳ 검증 중",
    STATUS_UNLINKED: "검증 불가 (fingerprint 미연결)",
}


@dataclass
class FixVerification:
    fix_event_id: str
    fix_title: str
    fix_source_type: str
    fixed_at: datetime
    fingerprint: Optional[str]
    status: str
    window_days: int
    recurred_at: Optional[datetime] = None
    recurrence_count: int = 0

    def to_dict(self) -> dict:
        return {
            "fix_event_id": self.fix_event_id,
            "fix_title": self.fix_title,
            "fix_source_type": self.fix_source_type,
            "fixed_at": self.fixed_at.isoformat(),
            "fingerprint": self.fingerprint,
            "status": self.status,
            "status_label": STATUS_LABELS.get(self.status, self.status),
            "window_days": self.window_days,
            "recurred_at": self.recurred_at.isoformat() if self.recurred_at else None,
            "recurrence_count": self.recurrence_count,
        }


def resolve_status(
    fixed_at: datetime,
    recurrence_times: Sequence[datetime],
    *,
    now: datetime,
    window_days: int,
) -> tuple[str, Optional[datetime], int]:
    """fix 시점과 재발 시각들로 상태 판정. 순수 함수 — 테스트 대상."""
    deadline = fixed_at + timedelta(days=window_days)
    hits = sorted(t for t in recurrence_times if fixed_at < t <= deadline)
    if hits:
        return STATUS_RECURRED, hits[0], len(hits)
    if now >= deadline:
        return STATUS_VERIFIED, None, 0
    return STATUS_PENDING, None, 0


def extract_fingerprints(canonical: Optional[dict]) -> list[str]:
    """fix 이벤트 canonical 에서 연결 fingerprint 목록 추출."""
    c = canonical or {}
    fps: list[str] = []
    multi = c.get("before_log_signatures")
    if isinstance(multi, list):
        fps.extend(str(f) for f in multi if f)
    single = c.get("before_log_signature")
    if single and str(single) not in fps:
        fps.append(str(single))
    return fps


def verify_fixes(
    session: Session,
    *,
    now: Optional[datetime] = None,
    lookback_days: Optional[int] = None,
    window_days: Optional[int] = None,
) -> list[FixVerification]:
    """lookback 기간 내 fix 이벤트를 검증. 읽기 전용 (커밋 없음).

    lookback 기본값은 window*2 — 지난주 fix 가 이번 주 뉴스레터에서
    verified/recurred 판정을 받을 수 있도록.
    """
    now = now or datetime.now(timezone.utc)
    window = window_days or settings.fix_verification_window_days
    lookback = lookback_days or window * 2
    since = now - timedelta(days=lookback)

    fixes: list[IngestionEvent] = list(session.scalars(
        select(IngestionEvent)
        .where(IngestionEvent.source_type.in_(
            [SOURCE_AUTO_TOBE_COMMIT, SOURCE_AUTO_TOBE_JOURNAL]))
        .where(IngestionEvent.occurred_at >= since)
        .order_by(IngestionEvent.occurred_at.desc())
    ))

    results: list[FixVerification] = []
    for fix in fixes:
        fps = extract_fingerprints(fix.canonical)
        if not fps:
            results.append(FixVerification(
                fix_event_id=str(fix.id),
                fix_title=fix.title or "(제목 없음)",
                fix_source_type=fix.source_type,
                fixed_at=fix.occurred_at,
                fingerprint=None,
                status=STATUS_UNLINKED,
                window_days=window,
            ))
            continue

        for fp in fps:
            recurrences = list(session.scalars(
                select(IngestionEvent.occurred_at)
                .where(IngestionEvent.source_type == SOURCE_LOGANALYZER)
                .where(IngestionEvent.category == "error_group")
                .where(IngestionEvent.canonical["fingerprint"].astext == fp)
                .where(IngestionEvent.occurred_at > fix.occurred_at)
            ))
            status, recurred_at, count = resolve_status(
                fix.occurred_at, recurrences, now=now, window_days=window,
            )
            results.append(FixVerification(
                fix_event_id=str(fix.id),
                fix_title=fix.title or "(제목 없음)",
                fix_source_type=fix.source_type,
                fixed_at=fix.occurred_at,
                fingerprint=fp,
                status=status,
                window_days=window,
                recurred_at=recurred_at,
                recurrence_count=count,
            ))
    return results


def record_chunk_verification(verifications: list[FixVerification]) -> int:
    """검증 결과를 corpus_fixes 청크 metadata_json 에 누적 (자체 세션·커밋).

    pending/unlinked 는 기록하지 않고, 확정 판정(verified/recurred)만 남긴다.
    """
    final = [v for v in verifications
             if v.status in (STATUS_VERIFIED, STATUS_RECURRED)]
    if not final:
        return 0
    updated = 0
    with SessionLocal() as session:
        for v in final:
            chunks = list(session.scalars(
                select(NewsletterChunk)
                .where(NewsletterChunk.event_id == uuid.UUID(v.fix_event_id))
                .where(NewsletterChunk.collection == COLLECTION_FIXES)
            ))
            for chunk in chunks:
                meta = dict(chunk.metadata_json or {})
                meta["verification"] = {
                    "status": v.status,
                    "fingerprint": v.fingerprint,
                    "recurrence_count": v.recurrence_count,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }
                chunk.metadata_json = meta
                updated += 1
        session.commit()
    return updated


def format_verification_block(verifications: list[FixVerification]) -> str:
    """stage-3 compose 프롬프트에 넣을 결정적 검증 블록."""
    if not verifications:
        return "(효과 검증 데이터 없음)"
    lines: list[str] = []
    for v in verifications:
        parts = [f"- {v.fix_title} — {STATUS_LABELS.get(v.status, v.status)}"]
        if v.fingerprint:
            parts.append(f"fingerprint={v.fingerprint}")
        if v.status == STATUS_RECURRED and v.recurred_at:
            parts.append(
                f"재발 {v.recurrence_count}회 (최초 {v.recurred_at.date().isoformat()})"
            )
        lines.append(" · ".join(parts))
    return "\n".join(lines)
