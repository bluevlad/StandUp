"""Tech Trend connector — 기술 동향 통합 수집.

두 채널을 섞어 `corpus_tech` 코퍼스를 만든다:

1. **Medium Daily Digest 리포트** (`medium-digest-agent` 가 생성한 Markdown)
   — 메일 수집 자체는 medium-digest-agent 가 담당하고, StandUp 은 그 산출물만 흡수.
2. **Google News RSS / Naver News API** 키워드 검색
   — `TECH_TREND_KEYWORDS` 단위로 최근 동향 보강. Medium Digest 가 비어 있어도
   동작하도록 별도 채널로 운영.

`source_type` 두 종을 사용:
- `medium_digest_report` — 디지스트에서 흡수한 LLM 분석 리포트 1건
- `tech_news_article` — 외부 뉴스 기사 1건

두 종 모두 `corpus_tech` 컬렉션으로 색인되어 합성 단계의 RAG 검색에 사용된다.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from ...core.config import settings
from ...models.insight import (
    COLLECTION_TECH,
    SOURCE_MEDIUM_DIGEST_REPORT,
    SOURCE_TECH_NEWS_ARTICLE,
)
from ...services.medium_digest_reader import (
    DigestReport,
    MediumDigestReaderService,
)
from ...services.tech_news_search import (
    KeywordSearchResult,
    NewsArticle,
    TechNewsSearchService,
)
from ..base import Connector
from ..schemas import CanonicalEvent, ChunkSpec, FetchResult

logger = logging.getLogger(__name__)

# 검색 결과의 발행일이 윈도우 양 끝에서 며칠 어긋나도 흡수.
_BUFFER = timedelta(days=2)


class TechTrendConnector(Connector):
    name = "tech_trend"

    def __init__(
        self,
        keywords: list[str],
        reports_dir: str = "",
        digest_reader: Optional[MediumDigestReaderService] = None,
        news_service: Optional[TechNewsSearchService] = None,
    ):
        self.keywords = [k for k in keywords if k]
        self.reports_dir = reports_dir
        self.digest_reader = digest_reader or MediumDigestReaderService(
            reports_dir=reports_dir, keywords=self.keywords,
        )
        self.news_service = news_service or TechNewsSearchService()

    def fetch(self, since: datetime, until: datetime) -> FetchResult:
        started = datetime.now(timezone.utc)
        events: list[CanonicalEvent] = []

        # 1. Medium Digest 리포트 흡수
        try:
            digest_reports = self.digest_reader.list_reports(since, until)
        except Exception as e:  # noqa: BLE001 — 외부 의존성 장애 흡수
            logger.warning("tech_trend digest 읽기 실패: %s", e)
            digest_reports = []

        for report in digest_reports:
            events.append(self._digest_to_event(report))

        # 2. 키워드별 뉴스 검색 (키워드 비어있으면 skip)
        if self.keywords:
            try:
                news_results = self.news_service.search_many(self.keywords)
            except Exception as e:  # noqa: BLE001
                logger.warning("tech_trend news 검색 실패: %s", e)
                news_results = {}
            for keyword, kwres in news_results.items():
                events.extend(self._news_to_events(keyword, kwres, since, until))

        logger.info(
            "tech_trend: digest=%d, news=%d (keywords=%s)",
            len(digest_reports),
            sum(1 for e in events if e.source_type == SOURCE_TECH_NEWS_ARTICLE),
            ",".join(self.keywords),
        )

        return FetchResult(
            events=events, connector_name=self.name,
            started_at=started, finished_at=datetime.now(timezone.utc),
        )

    # ── Digest 리포트 변환 ────────────────────────────────────────────────
    def _digest_to_event(self, report: DigestReport) -> CanonicalEvent:
        # corpus_tech 청크 — RAG 가 충분히 활용할 수 있도록 핵심 섹션을 텍스트화
        body_lines: list[str] = [f"[Digest] {report.title}"]
        if report.keyword:
            body_lines.append(f"키워드: {report.keyword}")
        if report.category:
            body_lines.append(f"카테고리: {report.category}")
        if report.priority:
            body_lines.append(f"우선순위: {report.priority}")
        if report.tech_description:
            body_lines.append("\n## 기술 설명\n" + report.tech_description)
        if report.target_scope:
            body_lines.append("\n## 적용 대상\n" + report.target_scope)
        if report.changes:
            body_lines.append("\n## 변경 사항\n" + report.changes)
        if report.risks:
            body_lines.append("\n## 리스크\n" + report.risks)
        chunk_text = "\n".join(body_lines)

        canonical = {
            "title": report.title,
            "keyword": report.keyword,
            "category": report.category,
            "priority": report.priority,
            "difficulty": report.difficulty,
            "maturity": report.maturity,
            "source_newsletter": report.source_newsletter,
            "references": report.references,
            "tech_description": report.tech_description,
            "current_state": report.current_state,
            "target_scope": report.target_scope,
            "changes": report.changes,
            "expected_effects": report.expected_effects,
            "risks": report.risks,
            "pilot_scope": report.pilot_scope,
            "file_path": str(report.file_path),
            # PR-SU-11 — medium-digest-agent v2 새 필드
            "importance_score": report.importance_score,
            "importance_factors": report.importance_factors,
            "interpretation_core": report.interpretation_core,
            "interpretation_why": report.interpretation_why,
            "interpretation_takeaways": report.interpretation_takeaways,
        }

        return CanonicalEvent(
            source_type=SOURCE_MEDIUM_DIGEST_REPORT,
            source_id=report.source_id,
            occurred_at=report.occurred_at,
            title=report.title,
            source_url=f"file://{report.file_path}",
            service_tag=None,
            severity=self._severity_from_priority(report.priority),
            category=report.category or "tech_proposal",
            canonical=canonical,
            raw_excerpt=report.short_excerpt,
            extra_chunks=[
                ChunkSpec(
                    text=chunk_text,
                    collection=COLLECTION_TECH,
                    metadata={
                        "source": "medium_digest_report",
                        "keyword": report.keyword,
                        "category": report.category,
                        "priority": report.priority,
                        "slug": report.slug,
                    },
                ),
            ],
        )

    # ── News article 변환 ─────────────────────────────────────────────────
    def _news_to_events(
        self,
        keyword: str,
        result: KeywordSearchResult,
        since: datetime,
        until: datetime,
    ) -> list[CanonicalEvent]:
        out: list[CanonicalEvent] = []
        for article in result.articles:
            occurred_at = article.published_at or datetime.now(timezone.utc)
            # tz-naive 인 경우 UTC 로 보정
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=timezone.utc)
            # 윈도우 외 기사는 스킵 (검색이 더 넓게 잡았을 수 있음)
            if occurred_at < since - _BUFFER or occurred_at > until + _BUFFER:
                continue

            url = article.url or ""
            url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16] if url else ""
            source_id = f"{article.source}:{keyword}:{url_hash}" if url_hash \
                else f"{article.source}:{keyword}:{article.fingerprint}"

            chunk_text = (
                f"[Tech News:{article.source}] {article.title}\n"
                f"키워드: {keyword}\n"
                f"{article.description}"
            )

            out.append(CanonicalEvent(
                source_type=SOURCE_TECH_NEWS_ARTICLE,
                source_id=source_id,
                occurred_at=occurred_at,
                title=article.title,
                source_url=url or None,
                service_tag=None,
                severity="info",
                category="tech_news",
                canonical={
                    "keyword": keyword,
                    "source": article.source,  # google|naver
                    "description": article.description,
                    "published_at": occurred_at.isoformat(),
                },
                raw_excerpt=article.description[:240],
                extra_chunks=[
                    ChunkSpec(
                        text=chunk_text,
                        collection=COLLECTION_TECH,
                        metadata={
                            "source": "tech_news_article",
                            "news_source": article.source,
                            "keyword": keyword,
                        },
                    ),
                ],
            ))
        return out

    @staticmethod
    def _severity_from_priority(priority: str) -> str | None:
        if not priority:
            return None
        p = priority.strip().lower()
        if p in ("critical", "high", "medium", "low"):
            return p
        # 한글 표기 매핑
        return {
            "긴급": "critical", "높음": "high", "중간": "medium", "낮음": "low",
        }.get(p)
