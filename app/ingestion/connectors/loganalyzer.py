"""
LogAnalyzer connector.

엔드포인트(이미 운영 중):
- GET /api/errors/groups        — fingerprint, service_group, error_type, severity,
                                   sample_message, first_seen, last_seen, occurrence_count, github_issue_url
- GET /api/errors/summary       — 종합 카운트 (KPI)
- GET /api/dashboard/summary    — 서비스별 24h 통계
- GET /api/errors/types         — error_type 분포
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from ...models.insight import COLLECTION_LOGS, SOURCE_LOGANALYZER
from ..base import Connector
from ..schemas import CanonicalEvent, ChunkSpec, FetchResult

logger = logging.getLogger(__name__)


class LogAnalyzerConnector(Connector):
    name = "loganalyzer"

    def __init__(self, base_url: str, window_days: int = 7, page_limit: int = 50,
                 excluded_services: set[str] | None = None):
        self.base_url = base_url.rstrip("/")
        self.window_days = window_days
        self.page_limit = page_limit
        # 집계/합성에서 제외할 service_group (소문자 비교)
        self.excluded_services = {s.lower() for s in (excluded_services or set())}

    def _get(self, path: str, **params) -> Any:
        url = f"{self.base_url}{path}"
        # trust_env=False — OrbStack 등 호스트 proxy 가 내부 호스트 호출까지 가로채는 사고 방지.
        with httpx.Client(timeout=30.0, trust_env=False) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            return r.json()

    def _parse_dt(self, s: str) -> datetime:
        # LogAnalyzer 는 ISO8601 (Z) 포맷
        return datetime.fromisoformat(s.replace("Z", "+00:00"))

    def fetch(self, since: datetime, until: datetime) -> FetchResult:
        started = datetime.now(timezone.utc)
        events: list[CanonicalEvent] = []

        hours = max(1, int((until - since).total_seconds() // 3600))

        # KPI 종합 — 단일 events 로 박아둠 (synthesis 가 활용)
        try:
            summary = self._get("/api/errors/summary", hours=hours)
            dash = self._get("/api/dashboard/summary")
            kpi_event = CanonicalEvent(
                source_type=SOURCE_LOGANALYZER,
                source_id=f"summary:{since.date()}_{until.date()}",
                occurred_at=until,
                title=f"LogAnalyzer 요약 ({hours}h)",
                source_url=f"{self.base_url}/api/dashboard/summary",
                service_tag=None,
                severity="info",
                category="kpi_summary",
                canonical={"summary": summary, "dashboard": dash, "hours": hours},
                raw_excerpt=(
                    f"errors={summary.get('total_errors', 0)} "
                    f"critical={summary.get('critical', 0)} "
                    f"high={summary.get('high', 0)}"
                ),
            )
            events.append(kpi_event)
        except Exception as e:  # noqa: BLE001
            logger.warning("LogAnalyzer summary 실패: %s", e)

        # 오류 그룹 (top N) — 각 그룹이 별도 이벤트
        try:
            groups = self._get(
                "/api/errors/groups",
                status="open",
                sort_by="occurrence_count",
                limit=self.page_limit,
            )
            for g in groups or []:
                svc = (g.get("service_group") or "").lower()
                if svc in self.excluded_services:
                    continue
                try:
                    evt = self._group_to_event(g, until)
                    if evt:
                        events.append(evt)
                except Exception as ge:  # noqa: BLE001
                    logger.warning("group 변환 실패 (id=%s): %s", g.get("id"), ge)
        except Exception as e:  # noqa: BLE001
            logger.warning("LogAnalyzer groups 실패: %s", e)

        # 에러 타입 분포 — 한 이벤트로
        try:
            types = self._get("/api/errors/types", days=max(1, hours // 24))
            events.append(CanonicalEvent(
                source_type=SOURCE_LOGANALYZER,
                source_id=f"types:{since.date()}_{until.date()}",
                occurred_at=until,
                title="LogAnalyzer 에러 타입 분포",
                source_url=f"{self.base_url}/api/errors/types",
                category="error_types",
                severity="info",
                canonical={"types": types},
                raw_excerpt=", ".join(
                    f"{t.get('error_type')}({t.get('count')})"
                    for t in (types or [])[:5]
                ),
            ))
        except Exception as e:  # noqa: BLE001
            logger.warning("LogAnalyzer types 실패: %s", e)

        finished = datetime.now(timezone.utc)
        return FetchResult(
            events=events,
            connector_name=self.name,
            started_at=started,
            finished_at=finished,
        )

    def _group_to_event(self, g: dict, fallback_dt: datetime) -> CanonicalEvent | None:
        last_seen = g.get("last_seen")
        if last_seen:
            occurred = self._parse_dt(last_seen)
        else:
            occurred = fallback_dt

        sample = (g.get("sample_message") or "").strip()
        excerpt = sample[:240] + ("…" if len(sample) > 240 else "")

        chunk_text = (
            f"[{g.get('service_group') or 'unknown'}/{g.get('error_type') or 'unknown'}] "
            f"severity={g.get('severity')} "
            f"count={g.get('occurrence_count')} "
            f"first={g.get('first_seen')} last={g.get('last_seen')}\n"
            f"sample: {sample}"
        )

        return CanonicalEvent(
            source_type=SOURCE_LOGANALYZER,
            source_id=f"group:{g.get('fingerprint') or g.get('id')}",
            occurred_at=occurred,
            title=f"{g.get('service_group')} · {g.get('error_type')} (×{g.get('occurrence_count')})",
            source_url=g.get("github_issue_url") or f"{self.base_url}/api/errors/groups",
            service_tag=g.get("service_group"),
            severity=(g.get("severity") or "").lower() or None,
            category="error_group",
            canonical={
                "fingerprint": g.get("fingerprint"),
                "container_name": g.get("container_name"),
                "error_type": g.get("error_type"),
                "occurrence_count": g.get("occurrence_count"),
                "first_seen": g.get("first_seen"),
                "last_seen": g.get("last_seen"),
                "sample_message": sample,
                "status": g.get("status"),
                "github_issue_number": g.get("github_issue_number"),
            },
            raw_excerpt=excerpt,
            extra_chunks=[
                ChunkSpec(
                    text=chunk_text,
                    collection=COLLECTION_LOGS,
                    metadata={
                        "fingerprint": g.get("fingerprint"),
                        "service": g.get("service_group"),
                        "severity": g.get("severity"),
                    },
                ),
            ],
        )
