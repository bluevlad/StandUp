"""HopenTechBrief — 일일 cron orchestrator (PR6).

PR4 적합도 게이트와 PR5 detailer 를 *일일* 케이던스로 운영하는 별도 채널.
주간 Insight Newsletter 와 다음과 같이 분리:

| 항목 | 주간 Insight | **일일 HopenTechBrief** |
|------|--------------|-------------------------|
| 윈도우 | 최근 7일 | 최근 24h (env로 조정) |
| 합성 | exaone3.5 cascade 풀세트 | tech_topics 추출만 |
| 내용 | LogAnalyzer / GitHub QA / Auto-Tobe 통합 | HopenVision 적용 토픽 한정 |
| 메일 채널 | report_types LIKE '%insight%' | **report_types LIKE '%hopen_tech%'** |
| 토픽 깊이 | 키워드 + 디지스트 hint | **+ Mermaid + 사례 + PoC 힌트** |
| 자동 DevPlan | env 토글 | env 토글 (별도) |

흐름:
1. IngestionHub.run() 으로 24h 윈도우의 medium_digest_report + tech_news_article 흡수
2. recent IngestionEvent → `_collect_tech_topics` 로 토픽 묶음
3. `propose_from_tech_topics` 로 게이트 + detailer + (옵션) DevPlan 초안화
4. 통과 토픽들로 `hopen_tech_brief.html` 카드 렌더
5. `report_types LIKE '%hopen_tech%'` 수신자에게 발송
6. Newsletter 행 저장 (subject prefix 로 일일/주간 구분)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import now_kst, settings
from ..core.database import SessionLocal
from ..ingestion.hub import IngestionHub
from ..models.insight import (
    IngestionEvent, Newsletter,
    SOURCE_MEDIUM_DIGEST_REPORT, SOURCE_TECH_NEWS_ARTICLE,
)
from ..newsletter.sender import SendSummary, send_hopen_tech_brief
from ..services.hopenvision_proposal_service import (
    ProposalResult, propose_from_tech_topics,
)
from ..synthesis.pipeline import TechTopic, _collect_tech_topics

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
_jinja = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


@dataclass
class DailyBriefResult:
    period_start: date
    period_end: date
    window_hours: int
    proposals: list[ProposalResult]
    eligible: int
    filtered_out: int
    newsletter_id: Optional[str] = None
    send: Optional[SendSummary] = None
    dry_run: bool = False
    skipped_reason: Optional[str] = None  # "no_eligible_topics" 등


# ── 윈도우 + 이벤트 조회 ──────────────────────────────────────────────────

def _window_range(window_hours: int) -> tuple[datetime, datetime]:
    """now-window ~ now (UTC)."""
    until = datetime.now(timezone.utc)
    since = until - timedelta(hours=window_hours)
    return since, until


def _fetch_recent_tech_events(
    session: Session, since: datetime, until: datetime,
) -> list[IngestionEvent]:
    """tech_trend 출처(2종) 만 윈도우로 조회."""
    q = (
        select(IngestionEvent)
        .where(IngestionEvent.occurred_at >= since)
        .where(IngestionEvent.occurred_at < until)
        .where(IngestionEvent.source_type.in_(
            [SOURCE_MEDIUM_DIGEST_REPORT, SOURCE_TECH_NEWS_ARTICLE]
        ))
        .order_by(IngestionEvent.occurred_at.desc())
        .limit(200)
    )
    return list(session.scalars(q))


# ── 렌더링 ────────────────────────────────────────────────────────────────

def _proposals_to_template_topics(
    proposals: list[ProposalResult],
    tech_topics: list[TechTopic],
) -> list[dict]:
    """eligible (generated|accepted) 만 카드 dict 로 변환.

    proposals 와 tech_topics 는 같은 keyword 순서로 매칭된다 (propose_from_tech_topics
    의 결과 순서와 입력 topics 의 순서가 일치한다는 전제).
    """
    keyword_to_topic = {t.keyword: t for t in tech_topics}
    cards: list[dict] = []
    for p in proposals:
        if p.status == "filtered_out":
            continue
        # cluster_keywords 가 [topic.keyword] 이므로 매칭
        kw = (p.cluster_key or "").replace("tech:", "", 1) or ""
        # 화면 표시용 원본 키워드를 tech_topics 에서 회수
        t = next(
            (t for t in tech_topics
             if t.keyword.lower().replace(" ", "-").startswith(kw)),
            None,
        )
        if t is None:
            # 매칭 실패 시에도 cluster_key 의 slug 를 그대로 사용
            display_keyword = kw
            digest_title = ""
            digest_summary = ""
        else:
            display_keyword = t.keyword
            digest_title = t.digest_title
            digest_summary = t.digest_summary

        cards.append({
            "keyword": display_keyword,
            "priority": (None
                         if (p.priority or "").lower() not in
                            ("critical", "high", "medium", "low")
                         else (p.priority or "").lower()),
            "impact_area": p.impact_area or "",
            "fitness_score": p.fitness_score or 0,
            "effort_hours": p.effort_hours,
            "digest_title": digest_title,
            "digest_summary": digest_summary,
            "diagnosis": p.diagnosis or "",
            "diagram_mermaid": p.diagram_mermaid or "",
            "case_studies": p.case_studies or [],
            "code_hints": p.code_hints or [],
            "candidate_modules": p.candidate_modules or [],
            "risks": p.risks or [],
        })
    return cards


def render_hopen_tech_brief(
    proposals: list[ProposalResult],
    tech_topics: list[TechTopic],
    *,
    period: date,
    eligible: int,
    filtered_out: int,
) -> dict:
    """proposals + topics → {subject, headline, html}."""
    kw_list = [t.keyword for t in tech_topics][:3]
    keywords_label = ", ".join(kw_list) if kw_list else "(no topics)"
    subject = (
        f"{settings.hopen_brief_subject_prefix} "
        f"{period.isoformat()} · {keywords_label}"
    )
    headline = (
        f"HopenTechBrief — {period.isoformat()} · "
        f"통과 {eligible}건 / 필터 {filtered_out}건"
    )
    template = _jinja.get_template("hopen_tech_brief.html")
    html = template.render(
        subject=subject,
        headline=headline,
        generated_at=now_kst().strftime("%Y-%m-%d %H:%M KST"),
        filtered_out_count=filtered_out,
        topics=_proposals_to_template_topics(proposals, tech_topics),
    )
    return {"subject": subject, "headline": headline, "html": html}


# ── 메인 진입점 ──────────────────────────────────────────────────────────

def run_daily(
    *,
    dry_run: bool = False,
    window_hours: Optional[int] = None,
    skip_ingest: bool = False,
) -> DailyBriefResult:
    """일일 HopenTechBrief 1회 실행.

    Args:
        dry_run: True 면 메일 발송 없음 (DB 행은 저장).
        window_hours: 최근 N시간. None 이면 settings.hopen_brief_window_hours.
        skip_ingest: True 면 IngestionHub 호출을 건너뛴다 (이미 다른 곳에서 돌린 경우).
    """
    wh = window_hours if window_hours is not None else settings.hopen_brief_window_hours
    today_kst = now_kst().date()
    logger.info("=== HopenTechBrief Daily 시작 %s (window=%dh, dry_run=%s) ===",
                today_kst, wh, dry_run)

    # 1) Ingestion (tech_trend connector 만 의미 있음, 다른 채널도 같은 hub 라 함께 실행)
    if not skip_ingest:
        try:
            hub_result = IngestionHub(embed_chunks=True).run()
            logger.info("daily ingestion: new_events=%d new_chunks=%d",
                        hub_result.new_events, hub_result.new_chunks)
        except Exception as e:  # noqa: BLE001
            logger.warning("daily ingestion 실패 (브리프 계속): %s", e)

    # 2) 24h 윈도우의 tech 이벤트 → tech_topics
    since, until = _window_range(wh)
    with SessionLocal() as session:
        events = _fetch_recent_tech_events(session, since, until)

    tech_topics = _collect_tech_topics(events)
    logger.info("daily tech_topics 수집: events=%d, topics=%d",
                len(events), len(tech_topics))

    # 3) 게이트 + detailer + (옵션) DevPlan
    proposals: list[ProposalResult]
    with SessionLocal() as session:
        proposals = propose_from_tech_topics(
            session,
            tech_topics,
            auto_dev_plan=settings.tech_trend_auto_dev_plan,
            max_topics=settings.hopen_brief_max_per_day,
        )

    filtered_out = sum(1 for p in proposals if p.status == "filtered_out")
    eligible = len(proposals) - filtered_out
    logger.info("daily 결과 — 통과=%d, 필터=%d (threshold=%d)",
                eligible, filtered_out, settings.hopen_brief_fitness_threshold)

    # 4) 통과 0건이면 발송·저장 skip — 빈 메일 보내지 않음
    if eligible == 0:
        logger.info("통과 토픽 없음 — 발송 skip")
        return DailyBriefResult(
            period_start=today_kst, period_end=today_kst,
            window_hours=wh, proposals=proposals,
            eligible=eligible, filtered_out=filtered_out,
            dry_run=dry_run, skipped_reason="no_eligible_topics",
        )

    # 5) 렌더 + 저장
    rendered = render_hopen_tech_brief(
        proposals, tech_topics,
        period=today_kst, eligible=eligible, filtered_out=filtered_out,
    )

    nl_id: str
    with SessionLocal() as session:
        nl = Newsletter(
            period_start=today_kst,
            period_end=today_kst,
            subject=rendered["subject"],
            headline=rendered["headline"],
            html_body=rendered["html"],
            plain_summary=rendered["headline"],
            source_event_ids=[
                UUID(str(e.id)) for e in events
            ],
            kpis={},
            synthesis_meta={
                "channel": "hopen_tech",
                "window_hours": wh,
                "eligible": eligible,
                "filtered_out": filtered_out,
                "fitness_threshold": settings.hopen_brief_fitness_threshold,
                "topic_count": len(tech_topics),
            },
        )
        session.add(nl)
        session.commit()
        session.refresh(nl)
        nl_id = str(nl.id)

    # 6) 발송 (hopen_tech 채널 수신자)
    with SessionLocal() as session:
        nl_to_send = session.get(Newsletter, nl_id)
        if nl_to_send is None:
            raise RuntimeError(f"hopen_tech newsletter {nl_id} missing")
        send_result = send_hopen_tech_brief(nl_to_send, dry_run=dry_run)
    logger.info("daily send: %s", send_result)

    return DailyBriefResult(
        period_start=today_kst, period_end=today_kst,
        window_hours=wh, proposals=proposals,
        eligible=eligible, filtered_out=filtered_out,
        newsletter_id=nl_id, send=send_result, dry_run=dry_run,
    )


def run_daily_job() -> None:
    """APScheduler wrapper — 예외 흡수."""
    try:
        run_daily(dry_run=False)
    except Exception as e:  # noqa: BLE001
        logger.error("hopen_tech_brief daily 실패: %s", e, exc_info=True)
