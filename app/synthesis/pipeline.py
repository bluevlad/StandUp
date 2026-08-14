"""
3-stage synthesis pipeline.

입력: IngestionEvent 리스트 (지난 N일)
출력: SynthesisOutput — KPI, 분석 JSON, 최종 markdown 본문
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.database import SessionLocal
from ..models.insight import (
    COLLECTION_FIXES, COLLECTION_LOGS, COLLECTION_NEWSLETTERS, COLLECTION_QA,
    COLLECTION_TECH, IngestionEvent, SOURCE_LOGANALYZER,
    SOURCE_MEDIUM_DIGEST_REPORT, SOURCE_TECH_NEWS_ARTICLE,
)
from ..observability.llmops import LLMOpsClient, StageReport
from ..rag.retriever import retrieve, RetrievedChunk
from .ollama_client import chat
from .prompts import (
    ANALYZE_SYSTEM, ANALYZE_USER_TPL,
    COMPOSE_SYSTEM, COMPOSE_USER_TPL,
    SUMMARIZE_SYSTEM, SUMMARIZE_USER_TPL,
)

logger = logging.getLogger(__name__)

# LLMOps 보고용 클라이언트 (모듈 싱글톤). LLMOPS_API_KEY 부재 시 no-op.
_LLMOPS = LLMOpsClient(consumer_id="standup-weekly-newsletter")


@dataclass
class TechTopic:
    """tech_trend 이벤트 그룹 — 키워드 단위로 디지스트 1건 + 관련 뉴스 N건."""

    keyword: str
    digest_title: str = ""
    digest_priority: str = ""
    digest_category: str = ""
    digest_difficulty: str = ""
    digest_maturity: str = ""
    digest_summary: str = ""
    digest_target_scope: str = ""
    digest_risks: str = ""
    digest_url: str = ""
    digest_event_id: str = ""
    news_articles: list[dict] = field(default_factory=list)
    # PR-SU-11 — medium-digest-agent v2 새 필드 (없으면 비어있음, 안전 default).
    importance_score: Optional[int] = None
    importance_factors: list[str] = field(default_factory=list)
    interpretation_core: str = ""
    interpretation_why: str = ""
    interpretation_takeaways: list[str] = field(default_factory=list)


@dataclass
class SynthesisOutput:
    period_start: date
    period_end: date
    headline: str
    markdown: str
    kpis: dict
    analysis: dict
    summaries: list[str]
    source_event_ids: list[str]
    rag_refs: list[dict]
    tech_topics: list[TechTopic] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


def _format_event_for_summary(e: IngestionEvent) -> str:
    parts = [f"- 제목: {e.title}"]
    if e.service_tag:
        parts.append(f"  서비스: {e.service_tag}")
    if e.severity:
        parts.append(f"  심각도: {e.severity}")
    if e.category:
        parts.append(f"  카테고리: {e.category}")
    if e.raw_excerpt:
        parts.append(f"  본문: {e.raw_excerpt}")
    if e.source_url:
        parts.append(f"  source_url: {e.source_url}")
    parts.append(f"  발생: {e.occurred_at.isoformat()}")
    return "\n".join(parts)


def _extract_kpis(events: list[IngestionEvent], session: Optional[Session] = None) -> dict:
    """기간 내 이벤트 자체 집계 + 가장 최근 LogAnalyzer kpi_summary (윈도우 무관)."""
    kpis: dict = {
        "total_events": len(events),
        "by_severity": {},
        "by_service": {},
        "by_source": {},
    }
    excluded = {s.lower() for s in settings.loganalyzer_excluded_services}
    for e in events:
        # 합성용 집계에서도 제외 서비스 제거
        if e.service_tag and e.service_tag.lower() in excluded:
            continue
        if e.severity:
            kpis["by_severity"][e.severity] = kpis["by_severity"].get(e.severity, 0) + 1
        if e.service_tag:
            kpis["by_service"][e.service_tag] = kpis["by_service"].get(e.service_tag, 0) + 1
        kpis["by_source"][e.source_type] = kpis["by_source"].get(e.source_type, 0) + 1

    # kpi_summary 는 fetch 시점 = now 로 박혀있어 period_end 이후에 떨어짐 →
    # 윈도우 무관하게 가장 최근 1건을 별도 조회
    if session is not None:
        latest_summary = session.execute(
            select(IngestionEvent)
            .where(IngestionEvent.source_type == SOURCE_LOGANALYZER)
            .where(IngestionEvent.category == "kpi_summary")
            .order_by(IngestionEvent.occurred_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest_summary is not None:
            kpis["loganalyzer_summary"] = latest_summary.canonical.get("summary", {})
            kpis["loganalyzer_dashboard"] = latest_summary.canonical.get("dashboard", {})

    return kpis


def _kpi_block(kpis: dict) -> str:
    lines: list[str] = []
    if "loganalyzer_summary" in kpis:
        s = kpis["loganalyzer_summary"]
        lines.append(
            f"LogAnalyzer: total={s.get('total_errors', 0)}, "
            f"critical={s.get('critical', 0)}, high={s.get('high', 0)}, "
            f"open_groups={s.get('open_groups', 0)}"
        )
    if kpis.get("by_severity"):
        lines.append(
            "심각도 분포: " +
            ", ".join(f"{k}={v}" for k, v in sorted(kpis["by_severity"].items()))
        )
    if kpis.get("by_service"):
        top = sorted(kpis["by_service"].items(), key=lambda x: -x[1])[:5]
        lines.append("서비스 top: " + ", ".join(f"{k}({v})" for k, v in top))
    if kpis.get("by_source"):
        lines.append(
            "소스: " + ", ".join(f"{k}={v}" for k, v in kpis["by_source"].items())
        )
    return "\n".join(lines) or "(no kpi)"


def _stage1_summarize(events: list[IngestionEvent]) -> list[str]:
    """이벤트들을 batch 단위로 요약."""
    if not events:
        return []
    summaries: list[str] = []
    BATCH = 10
    for i in range(0, len(events), BATCH):
        batch = events[i:i + BATCH]
        events_text = "\n\n".join(_format_event_for_summary(e) for e in batch)
        result = chat(
            model=settings.ollama_model_summarize,
            system=SUMMARIZE_SYSTEM,
            user=SUMMARIZE_USER_TPL.format(events_text=events_text),
            temperature=0.2,
            max_tokens=1024,
            # think=False: gemma4 계열 reasoning 억제 — 요약이 max_tokens 소진으로 비는 것 방지
            think=False,
        )
        if result.ok and result.text:
            summaries.append(result.text)
        else:
            # 실패 시 raw 요약으로 폴백 (LLM 없이도 본문 작성 가능하게)
            summaries.append("\n".join(
                f"- {e.title} [REF:{e.source_url or ''}]"
                for e in batch
            ))
    return summaries


def _stage2_analyze(summaries: list[str], kpis: dict) -> dict:
    if not summaries:
        return {"recurring": [], "new": [], "improvements": [], "actions": []}
    user = ANALYZE_USER_TPL.format(
        summaries="\n\n".join(summaries),
        kpi_block=_kpi_block(kpis),
    )
    result = chat(
        model=settings.ollama_model_analyze,
        system=ANALYZE_SYSTEM,
        user=user,
        temperature=0.2,
        max_tokens=2048,
    )
    if not result.ok or not result.text:
        return {"recurring": [], "new": [], "improvements": [], "actions": [],
                "_error": result.error or "empty"}
    # JSON 추출 — 모델이 markdown 펜스로 감쌀 수 있음
    raw = result.text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        # ```json\n{...}\n```
        if raw.lower().startswith("json"):
            raw = raw[4:].lstrip()
        raw = raw.rstrip("`").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 첫 { 부터 마지막 } 까지 추출 시도
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e != -1 and e > s:
            try:
                return json.loads(raw[s:e + 1])
            except json.JSONDecodeError:
                pass
        logger.warning("stage2 JSON 파싱 실패, raw 길이=%d", len(raw))
        return {"recurring": [], "new": [], "improvements": [], "actions": [],
                "_raw": raw[:1000]}


def _retrieve_rag_context(session: Session, query: str) -> list[RetrievedChunk]:
    """과거 뉴스레터 + fix 사례 + 기술 토픽 코퍼스 검색."""
    refs: list[RetrievedChunk] = []
    refs.extend(retrieve(session, query, COLLECTION_NEWSLETTERS, top_k=3))
    refs.extend(retrieve(session, query, COLLECTION_FIXES, top_k=3))
    refs.extend(retrieve(session, query, COLLECTION_TECH, top_k=3))
    return refs


def _collect_tech_topics(events: list[IngestionEvent]) -> list[TechTopic]:
    """tech_trend 이벤트(digest + news)를 키워드 단위로 그룹핑.

    각 키워드(소문자 정규화)에 대해:
    - 가장 최근 medium_digest_report 1건을 대표 디지스트로 선택
    - 같은 키워드의 tech_news_article 들을 news_articles 로 매핑
    """
    digest_by_kw: dict[str, IngestionEvent] = {}
    news_by_kw: dict[str, list[IngestionEvent]] = {}
    display_by_kw: dict[str, str] = {}  # 정규화 키 → 화면 표시용 원문 케이스

    for ev in events:
        kw = (ev.canonical or {}).get("keyword") or ""
        kw_norm = kw.strip().lower()
        if not kw_norm:
            continue
        # 디지스트가 있으면 그쪽 케이스를 우선 사용. 없으면 처음 본 뉴스의 케이스.
        if kw_norm not in display_by_kw or ev.source_type == SOURCE_MEDIUM_DIGEST_REPORT:
            display_by_kw[kw_norm] = kw.strip()
        if ev.source_type == SOURCE_MEDIUM_DIGEST_REPORT:
            existing = digest_by_kw.get(kw_norm)
            if existing is None or ev.occurred_at > existing.occurred_at:
                digest_by_kw[kw_norm] = ev
        elif ev.source_type == SOURCE_TECH_NEWS_ARTICLE:
            news_by_kw.setdefault(kw_norm, []).append(ev)

    if not digest_by_kw and not news_by_kw:
        return []

    # 키워드 union — 디지스트 우선 정렬, 다음으로 뉴스만 있는 키워드
    all_kws = list(digest_by_kw.keys()) + [
        k for k in news_by_kw.keys() if k not in digest_by_kw
    ]
    topics: list[TechTopic] = []
    for kw in all_kws:
        digest_ev = digest_by_kw.get(kw)
        news_evs = news_by_kw.get(kw, [])
        # 뉴스는 최신순 정렬, 키워드당 최대 5건만 노출
        news_evs.sort(key=lambda e: e.occurred_at, reverse=True)
        news_evs = news_evs[:5]

        topic = TechTopic(keyword=display_by_kw.get(kw, kw))
        if digest_ev is not None:
            c = digest_ev.canonical or {}
            topic.digest_title = digest_ev.title or ""
            topic.digest_priority = c.get("priority", "")
            topic.digest_category = c.get("category", "")
            topic.digest_difficulty = c.get("difficulty", "")
            topic.digest_maturity = c.get("maturity", "")
            topic.digest_summary = (c.get("tech_description") or "")[:600]
            topic.digest_target_scope = (c.get("target_scope") or "")[:600]
            topic.digest_risks = (c.get("risks") or "")[:600]
            topic.digest_url = digest_ev.source_url or ""
            topic.digest_event_id = str(digest_ev.id)
            # PR-SU-11 — v2 필드 (medium-digest-agent PR-MDA-2/3 산출). canonical 에
            # 없을 수도 있으므로 안전 fallback.
            score_raw = c.get("importance_score")
            if isinstance(score_raw, (int, float)):
                topic.importance_score = int(score_raw)
            factors = c.get("importance_factors") or []
            if isinstance(factors, list):
                topic.importance_factors = [str(f)[:200] for f in factors[:5]]
            topic.interpretation_core = (c.get("interpretation_core") or "")[:600]
            topic.interpretation_why = (c.get("interpretation_why") or "")[:400]
            takeaways = c.get("interpretation_takeaways") or []
            if isinstance(takeaways, list):
                topic.interpretation_takeaways = [str(t)[:200] for t in takeaways[:4]]
        for nev in news_evs:
            nc = nev.canonical or {}
            topic.news_articles.append({
                "title": nev.title,
                "url": nev.source_url or "",
                "source": nc.get("source", ""),
                "description": (nc.get("description") or "")[:240],
                "published_at": (
                    nev.occurred_at.isoformat()
                    if nev.occurred_at else ""
                ),
            })
        topics.append(topic)

    # 우선순위 high/critical 을 먼저, 그 다음 디지스트 있는 것, 그 다음 뉴스 수
    _PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "": 9}
    topics.sort(key=lambda t: (
        _PRIORITY_ORDER.get((t.digest_priority or "").lower(), 9),
        0 if t.digest_title else 1,
        -len(t.news_articles),
    ))
    return topics


def _format_rag_block(refs: list[RetrievedChunk]) -> str:
    if not refs:
        return "(과거 사례 없음)"
    lines: list[str] = []
    for r in refs:
        head = r.source_title or r.collection
        url = r.source_url or ""
        lines.append(
            f"- {head} (dist={r.distance:.3f}): "
            f"{r.chunk_text[:200].replace(chr(10), ' ')} [REF:{url}]"
        )
    return "\n".join(lines)


def _stage3_compose(
    period_start: date,
    period_end: date,
    kpis: dict,
    analysis: dict,
    rag_refs: list[RetrievedChunk],
    summaries_top: str,
) -> str:
    user = COMPOSE_USER_TPL.format(
        period_start=period_start.isoformat(),
        period_end=period_end.isoformat(),
        kpi_block=_kpi_block(kpis),
        analysis_json=json.dumps(analysis, ensure_ascii=False, indent=2),
        rag_block=_format_rag_block(rag_refs),
        summaries_top=summaries_top,
    )
    result = chat(
        model=settings.ollama_model_compose,
        system=COMPOSE_SYSTEM,
        user=user,
        temperature=0.5,
        max_tokens=2048,
    )
    if not result.ok or not result.text:
        return _fallback_markdown(period_start, period_end, kpis, analysis, rag_refs)
    return result.text


def _fallback_markdown(period_start, period_end, kpis, analysis, rag_refs) -> str:
    """LLM 실패 시 데이터만이라도 발송될 수 있도록."""
    lines = [
        f"# StandUp Insight {period_start} ~ {period_end}",
        "",
        "## 핵심 KPI",
        _kpi_block(kpis),
        "",
        "## 분석 (raw)",
        "```json",
        json.dumps(analysis, ensure_ascii=False, indent=2),
        "```",
    ]
    if rag_refs:
        lines.extend(["", "## 과거 사례", _format_rag_block(rag_refs)])
    lines.append("\n_(LLM 호출 실패 — 데이터만 표시. 운영자 확인 요망.)_")
    return "\n".join(lines)


_HEADLINE_PLACEHOLDERS = {"헤드라인", "제목", "headline", "title", "tbd", "todo"}


def _extract_headline(markdown: str) -> str:
    for line in markdown.splitlines():
        s = line.strip()
        if s.startswith("# ") and len(s) > 2:
            candidate = s[2:].strip()
            # placeholder 회피
            if candidate.lower().strip("()[]{}") in _HEADLINE_PLACEHOLDERS:
                continue
            if len(candidate) < 4:  # 너무 짧으면 placeholder 의심
                continue
            return candidate[:200]
    return "StandUp Insight 주간 보고"


def synthesize(
    period_start: date,
    period_end: date,
    session: Optional[Session] = None,
) -> SynthesisOutput:
    """기간 내 IngestionEvent 를 cascade 합성."""
    own_session = session is None
    if own_session:
        session = SessionLocal()

    # LLMOps 보고용 식별자 (cascade 1 회 = batch_run 1 건)
    llmops_started_at = datetime.now(timezone.utc)
    llmops_run_id = f"{llmops_started_at.isoformat()}-{os.getpid()}"

    try:
        start_dt = datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc)
        end_dt = datetime.combine(period_end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

        excluded = settings.loganalyzer_excluded_services  # set[str], lowercase
        q = (
            select(IngestionEvent)
            .where(IngestionEvent.occurred_at >= start_dt)
            .where(IngestionEvent.occurred_at < end_dt)
        )
        if excluded:
            # service_tag 가 NULL 이면 통과, 소문자 매칭으로 제외
            q = q.where(
                or_(
                    IngestionEvent.service_tag.is_(None),
                    func.lower(IngestionEvent.service_tag).notin_(list(excluded)),
                )
            )
        events: list[IngestionEvent] = list(session.scalars(
            q.order_by(IngestionEvent.occurred_at.desc()).limit(200)
        ))

        kpis = _extract_kpis(events, session=session)
        meta: dict = {
            "models": {
                "summarize": settings.ollama_model_summarize,
                "analyze": settings.ollama_model_analyze,
                "compose": settings.ollama_model_compose,
            },
            "event_count": len(events),
        }

        # Stage 1
        t0 = datetime.now()
        summaries = _stage1_summarize(events)
        meta["stage1_ms"] = int((datetime.now() - t0).total_seconds() * 1000)

        # Stage 2
        t0 = datetime.now()
        analysis = _stage2_analyze(summaries, kpis)
        meta["stage2_ms"] = int((datetime.now() - t0).total_seconds() * 1000)

        # RAG — 분석 결과의 텍스트로 과거 사례 검색
        rag_query_parts = []
        for r in (analysis.get("recurring") or [])[:3]:
            rag_query_parts.append(str(r.get("pattern") or ""))
        for a in (analysis.get("actions") or [])[:2]:
            rag_query_parts.append(str(a.get("what") or ""))
        rag_query = " ".join(p for p in rag_query_parts if p) or " ".join(
            e.title for e in events[:3]
        )
        rag_refs = _retrieve_rag_context(session, rag_query) if rag_query else []

        # Stage 3
        t0 = datetime.now()
        summaries_top = "\n\n".join(summaries[:3]) if summaries else "(요약 없음)"
        markdown = _stage3_compose(
            period_start, period_end, kpis, analysis, rag_refs, summaries_top,
        )
        meta["stage3_ms"] = int((datetime.now() - t0).total_seconds() * 1000)

        tech_topics = _collect_tech_topics(events)
        meta["tech_topic_count"] = len(tech_topics)

        result = SynthesisOutput(
            period_start=period_start,
            period_end=period_end,
            headline=_extract_headline(markdown),
            markdown=markdown,
            kpis=kpis,
            analysis=analysis,
            summaries=summaries,
            source_event_ids=[str(e.id) for e in events],
            rag_refs=[
                {
                    "chunk_id": r.chunk_id, "collection": r.collection,
                    "distance": r.distance, "source_url": r.source_url,
                    "title": r.source_title,
                }
                for r in rag_refs
            ],
            tech_topics=tech_topics,
            meta=meta,
        )

        # LLMOps 보고 (성공) — fire-and-forget, 실패해도 본 함수 영향 없음
        _LLMOPS.report(
            run_id=llmops_run_id,
            started_at=llmops_started_at,
            ended_at=datetime.now(timezone.utc),
            status="success",
            stages=[
                StageReport(name="summarize", model=settings.ollama_model_summarize,
                            duration_ms=meta.get("stage1_ms")),
                StageReport(name="analyze", model=settings.ollama_model_analyze,
                            duration_ms=meta.get("stage2_ms")),
                StageReport(name="compose", model=settings.ollama_model_compose,
                            duration_ms=meta.get("stage3_ms")),
            ],
            metrics={
                "event_count": meta.get("event_count", 0),
                "tech_topic_count": meta.get("tech_topic_count", 0),
                "summaries_count": len(summaries),
                "rag_ref_count": len(rag_refs),
                "markdown_len": len(markdown),
            },
        )
        return result
    except Exception as exc:
        # 실패도 보고 (단, raise 는 그대로)
        _LLMOPS.report(
            run_id=llmops_run_id,
            started_at=llmops_started_at,
            ended_at=datetime.now(timezone.utc),
            status="failure",
            error={"type": type(exc).__name__, "message": str(exc)[:500]},
        )
        raise
    finally:
        if own_session:
            session.close()
