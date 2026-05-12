"""
Insight Newsletter (v2) — 수동 트리거 + 상태 조회.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ....agents_v2.hopen_tech_brief import run_daily as run_daily_hopen_tech
from ....agents_v2.insight_newsletter import run_weekly
from ....core.database import get_db
from ....ingestion.hub import IngestionHub
from ....models.insight import IngestionEvent, Newsletter

router = APIRouter(prefix="/insight", tags=["insight"])


class IngestRunResponse(BaseModel):
    fetched: int
    new_events: int
    new_chunks: int
    per_connector: dict
    errors: list[str]


class WeeklyRunRequest(BaseModel):
    dry_run: bool = False
    period_start: Optional[date] = None
    period_end: Optional[date] = None


class WeeklyRunResponse(BaseModel):
    newsletter_id: str
    period_start: date
    period_end: date
    headline: str
    subject: str
    sent: int
    failed: int
    indexed_chunks: int
    stage_ms: dict


@router.post("/ingest/run", response_model=IngestRunResponse)
def trigger_ingest():
    """모든 활성 connector 즉시 1회 실행."""
    result = IngestionHub(embed_chunks=True).run()
    return IngestRunResponse(
        fetched=result.fetched,
        new_events=result.new_events,
        new_chunks=result.new_chunks,
        per_connector=result.per_connector,
        errors=result.errors,
    )


@router.post("/weekly/run", response_model=WeeklyRunResponse)
def trigger_weekly(req: WeeklyRunRequest):
    """주간 뉴스레터 즉시 1회 실행 (수동 테스트용)."""
    period = None
    if req.period_start and req.period_end:
        if req.period_start > req.period_end:
            raise HTTPException(400, "period_start > period_end")
        period = (req.period_start, req.period_end)
    res = run_weekly(dry_run=req.dry_run, period=period)
    return WeeklyRunResponse(
        newsletter_id=res.newsletter_id,
        period_start=res.period_start,
        period_end=res.period_end,
        headline=res.synthesis.headline,
        subject=f"(see newsletter id={res.newsletter_id})",
        sent=res.send.success,
        failed=res.send.failed,
        indexed_chunks=res.indexed_chunks,
        stage_ms={k: res.synthesis.meta.get(k) for k in
                  ("stage1_ms", "stage2_ms", "stage3_ms")},
    )


@router.get("/events")
def list_events(
    days: int = Query(7, ge=1, le=90),
    source_type: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    from datetime import datetime, timedelta, timezone
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = select(IngestionEvent).where(IngestionEvent.occurred_at >= since)
    if source_type:
        q = q.where(IngestionEvent.source_type == source_type)
    q = q.order_by(IngestionEvent.occurred_at.desc()).limit(limit)
    rows = db.scalars(q).all()
    return [
        {
            "id": str(r.id),
            "source_type": r.source_type,
            "source_id": r.source_id,
            "source_url": r.source_url,
            "occurred_at": r.occurred_at.isoformat(),
            "service_tag": r.service_tag,
            "severity": r.severity,
            "category": r.category,
            "title": r.title,
            "raw_excerpt": r.raw_excerpt,
        }
        for r in rows
    ]


@router.get("/newsletters")
def list_newsletters(limit: int = Query(20, ge=1, le=100),
                     db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Newsletter).order_by(Newsletter.created_at.desc()).limit(limit)
    ).all()
    return [
        {
            "id": str(r.id),
            "period_start": r.period_start.isoformat(),
            "period_end": r.period_end.isoformat(),
            "subject": r.subject,
            "headline": r.headline,
            "created_at": r.created_at.isoformat(),
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            "kpis": r.kpis,
        }
        for r in rows
    ]


@router.get("/newsletters/{newsletter_id}/preview", response_class=HTMLResponse)
def preview_newsletter(newsletter_id: str, db: Session = Depends(get_db)):
    nl = db.get(Newsletter, newsletter_id)
    if nl is None:
        raise HTTPException(404, "newsletter not found")
    return HTMLResponse(content=nl.html_body)


# ── HopenTechBrief 일일 채널 (PR6) ───────────────────────────────────────

class HopenBriefRunRequest(BaseModel):
    dry_run: bool = False
    window_hours: Optional[int] = None
    skip_ingest: bool = False
    # PR10 — 운영자 수동 트리거 시 캐시·평가 범위 조정.
    force_refresh: bool = False  # hopenvision_proposals 캐시 무시
    max_topics: Optional[int] = None  # 1회 평가 토픽 상한 (기본 settings.hopen_brief_max_per_day)


class HopenBriefRunResponse(BaseModel):
    newsletter_id: Optional[str]
    period: date
    window_hours: int
    eligible: int
    filtered_out: int
    sent: int
    failed: int
    skipped_reason: Optional[str] = None


@router.post("/hopen-brief/run", response_model=HopenBriefRunResponse)
def trigger_hopen_brief(req: HopenBriefRunRequest):
    """HopenTechBrief 일일 1회 즉시 실행 (수동 트리거 / dry-run).

    `force_refresh=true` 면 토픽 캐시(`hopenvision_proposals`) 를 무시하고 LLM 재호출.
    `max_topics` 로 1회 평가 토픽 상한 조정 (기본 `HOPEN_BRIEF_MAX_PER_DAY=3`).
    """
    res = run_daily_hopen_tech(
        dry_run=req.dry_run,
        window_hours=req.window_hours,
        skip_ingest=req.skip_ingest,
        force_refresh=req.force_refresh,
        max_topics=req.max_topics,
    )
    return HopenBriefRunResponse(
        newsletter_id=res.newsletter_id,
        period=res.period_start,
        window_hours=res.window_hours,
        eligible=res.eligible,
        filtered_out=res.filtered_out,
        sent=res.send.success if res.send else 0,
        failed=res.send.failed if res.send else 0,
        skipped_reason=res.skipped_reason,
    )
