"""
Insight-Newsletter Agent — 주간 orchestrator.

순서:
1. IngestionHub.run() — 외부 소스 수집 + 청크 임베딩
2. synthesis.synthesize() — 3-stage cascade
3. newsletter.builder.render_newsletter() — HTML 본문
4. Newsletter row 저장 + RAG 색인
5. newsletter.sender.send_newsletter() — 메일 발송
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
from ..newsletter.sender import SendSummary, send_newsletter
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
    send: SendSummary
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


def run_weekly(*, dry_run: bool = False, period: Optional[tuple[date, date]] = None) -> WeeklyRunResult:
    """주간 뉴스레터 1회 실행."""
    period_start, period_end = period or _last_week_window()
    logger.info("=== Insight Weekly 시작 %s ~ %s (dry_run=%s) ===",
                period_start, period_end, dry_run)

    # 1. Ingestion
    hub = IngestionHub(embed_chunks=True)
    hub_result = hub.run()
    logger.info("ingestion 완료: %s", hub_result.per_connector)

    # 2. Synthesis
    syn = synthesize(period_start, period_end)
    logger.info("synthesis 완료: events=%d stages=%s",
                len(syn.source_event_ids),
                {k: syn.meta.get(k) for k in ("stage1_ms", "stage2_ms", "stage3_ms")})

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

        # RAG 색인 — 발송 여부와 무관하게 자기참조 학습 가능하도록
        try:
            indexed = index_newsletter(session, nl)
            session.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("뉴스레터 RAG 색인 실패: %s", e)
            session.rollback()

    # 5. Send (dry_run 이면 발송 X)
    send_result: SendSummary
    with SessionLocal() as session:
        nl_to_send = session.get(Newsletter, nl_id)
        if nl_to_send is None:
            raise RuntimeError(f"newsletter {nl_id} 가 사라짐")
        send_result = send_newsletter(nl_to_send, dry_run=dry_run)
    logger.info("send 완료: %s", send_result)

    # 6. tech_topics → HopenVision 제안 (+ DevPlan 자동 초안화)
    #    LLM 호출이라 발송 이후로 미루고, 실패해도 주간 흐름은 막지 않는다.
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
            logger.info(
                "tech_topic 제안 %d건 생성 (auto_dev_plan=%s)",
                len(tech_proposals), settings.tech_trend_auto_dev_plan,
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
        send=send_result,
        indexed_chunks=indexed,
        tech_topic_proposals=tech_proposals,
    )


def run_weekly_job() -> None:
    """APScheduler 가 호출하는 wrapper — 예외 흡수."""
    try:
        run_weekly(dry_run=False)
    except Exception as e:  # noqa: BLE001
        logger.error("insight weekly 실패: %s", e, exc_info=True)
