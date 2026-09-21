"""
Insight-Newsletter Agent — 주간 orchestrator.

순서:
1. IngestionHub.run() — 외부 소스 수집 + 청크 임베딩
2. synthesis.synthesize() — 3-stage cascade
3. newsletter.builder.render_newsletter() — HTML 본문
4. Newsletter row 저장 + RAG 색인

StandUp 은 메일을 직접 발송하지 않는다 (2026-09-21 제거). 결과물은
`/api/v1/insight/newsletters` API 와 대시보드로만 노출되며, 외부 뉴스레터
(TechBriefing 등) 가 필요 시 pull 한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from ..core.config import now_kst, settings
from ..core.database import SessionLocal
from ..ingestion.hub import HubResult, IngestionHub
from ..models.insight import Newsletter
from ..newsletter.builder import render_newsletter
from ..rag.store import index_newsletter
from ..synthesis.pipeline import SynthesisOutput, synthesize

logger = logging.getLogger(__name__)


@dataclass
class WeeklyRunResult:
    period_start: date
    period_end: date
    hub: HubResult
    synthesis: SynthesisOutput
    newsletter_id: str
    indexed_chunks: int
    tech_topic_proposals: list = field(default_factory=list)


def _last_week_window() -> tuple[date, date]:
    """오늘 기준 직전 주 [월~일]. 월요일 09:00 발송 기준."""
    today = now_kst().date()
    # 오늘이 월요일이면 직전 월~일
    days_since_monday = today.weekday()  # 월=0
    this_monday = today - timedelta(days=days_since_monday)
    last_sunday = this_monday - timedelta(days=1)
    last_monday = last_sunday - timedelta(days=6)
    return last_monday, last_sunday


def run_weekly(*, period: Optional[tuple[date, date]] = None) -> WeeklyRunResult:
    """주간 뉴스레터 1회 실행 (합성 → 저장 → RAG 색인, 발송 없음)."""
    period_start, period_end = period or _last_week_window()
    logger.info("=== Insight Weekly 시작 %s ~ %s ===", period_start, period_end)

    # 1. Ingestion
    hub = IngestionHub(embed_chunks=True)
    hub_result = hub.run()
    logger.info("ingestion 완료: %s", hub_result.per_connector)

    # 2. Synthesis
    syn = synthesize(period_start, period_end)
    logger.info("synthesis 완료: events=%d stages=%s",
                len(syn.source_event_ids),
                {k: syn.meta.get(k) for k in ("stage1_ms", "stage2_ms", "stage3_ms")})

    # PR6 — 주간 newsletter 의 tech 섹션은 HopenVision 스택 매칭만 통과한 토픽으로
    # 축약. 일일 [HopenTechBrief] 가 깊이를 다루므로, 주간은 *얕은* 게이트로 무관
    # 토픽(Autonomous-QA-Agent / 머신비전 등) 만 컷.
    if syn.tech_topics:
        from ..services.tech_topic_filter import evaluate_topic
        original = len(syn.tech_topics)
        syn.tech_topics = [
            t for t in syn.tech_topics
            if evaluate_topic(
                t, use_llm=False,
                threshold=settings.weekly_tech_stack_min_score,
            ).eligible
        ]
        if len(syn.tech_topics) < original:
            logger.info(
                "weekly tech 섹션 축약: %d → %d (stack threshold=%d)",
                original, len(syn.tech_topics),
                settings.weekly_tech_stack_min_score,
            )

    # 3. Render
    rendered = render_newsletter(syn)

    # 4. Persist + RAG
    nl_id: str
    indexed = 0
    with SessionLocal() as session:
        nl = Newsletter(
            period_start=period_start,
            period_end=period_end,
            subject=rendered["subject"],
            headline=rendered["headline"],
            html_body=rendered["html"],
            plain_summary=rendered["plain_summary"],
            source_event_ids=[
                __import__("uuid").UUID(eid) for eid in syn.source_event_ids
            ] if syn.source_event_ids else [],
            kpis=syn.kpis,
            synthesis_meta={**syn.meta, "rag_refs": syn.rag_refs,
                            "analysis": syn.analysis},
        )
        session.add(nl)
        session.commit()
        session.refresh(nl)
        nl_id = str(nl.id)

        # RAG 색인 — 다음 호 작성 시 자기참조 비교용
        try:
            indexed = index_newsletter(session, nl)
            session.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("뉴스레터 RAG 색인 실패: %s", e)
            session.rollback()

    # 5. tech_topics → HopenVision 제안 (+ DevPlan 자동 초안화)
    #    LLM 호출이라 저장·색인 이후로 미루고, 실패해도 주간 흐름은 막지 않는다.
    tech_proposals: list = []
    if syn.tech_topics:
        try:
            from ..services.hopenvision_proposal_service import (
                propose_from_tech_topics,
            )
            with SessionLocal() as session:
                tech_proposals = propose_from_tech_topics(
                    session,
                    syn.tech_topics,
                    auto_dev_plan=settings.tech_trend_auto_dev_plan,
                    max_topics=settings.tech_trend_max_topics_per_run,
                )
            filtered_out = sum(
                1 for p in tech_proposals if getattr(p, "status", "") == "filtered_out"
            )
            generated = len(tech_proposals) - filtered_out
            logger.info(
                "tech_topic 처리 결과 — 통과=%d (auto_dev_plan=%s), "
                "filtered_out=%d (threshold=%d)",
                generated, settings.tech_trend_auto_dev_plan, filtered_out,
                settings.hopen_brief_fitness_threshold,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("tech_topic 제안 실패 (파이프라인은 계속): %s", e,
                           exc_info=True)

    logger.info("=== Insight Weekly 종료 ===")
    return WeeklyRunResult(
        period_start=period_start,
        period_end=period_end,
        hub=hub_result,
        synthesis=syn,
        newsletter_id=nl_id,
        indexed_chunks=indexed,
        tech_topic_proposals=tech_proposals,
    )


def run_weekly_job() -> None:
    """APScheduler 가 호출하는 wrapper — 예외 흡수."""
    try:
        run_weekly()
    except Exception as e:  # noqa: BLE001
        logger.error("insight weekly 실패: %s", e, exc_info=True)
