"""
HopenVision 적용 플랜 제안 서비스 (PR3).

두 가지 트리거:

1. **클러스터 기반** (기존, dashboard 수동) — `generate_proposal(cluster_key)`
   topic_cluster_service 의 클러스터 + 최근 hopenvision WorkItem context →
   LLM JSON {diagnosis, candidate_modules, risks, priority} → cache → 수락 시 DevPlan.

2. **기술 토픽 기반** (신규, 주간 orchestrator 자동) — `propose_from_tech_topics(topics)`
   tech_trend connector 가 수집한 Medium Digest + 뉴스 토픽 묶음을 같은 LLM 인터페이스로
   재사용. cluster_key 는 `tech:<slug>` prefix 로 구분되며, env 옵션에 따라 즉시 DevPlan
   초안화까지 자동 진행한다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..models.dev_plan import (
    DevPlan, DevPlanItem, PlanStatus, PlanItemStatus, PlanItemPriority,
)
from ..models.insight import HopenVisionProposal
from ..models.issue import WorkItem
from ..synthesis.ollama_client import chat
from .topic_cluster_service import get_topic_clusters

if TYPE_CHECKING:
    from ..synthesis.pipeline import TechTopic

logger = logging.getLogger(__name__)

HOPENVISION_REPO = "hopenvision"
HOPENVISION_PROJECT = "hopenvision"

_SYSTEM_PROMPT = """당신은 HopenVision 프로젝트의 시니어 엔지니어다. 외부에서 수집된
기술 토픽을 보고 HopenVision 코드베이스에 적용 가능한 구체적 플랜을 작성한다.

응답은 반드시 아래 JSON 스키마로만 답한다 — 다른 텍스트나 마크다운 코드블록 없이 순수 JSON.

{
  "diagnosis": "현재 HopenVision 의 관련 영역에 대한 진단 (3-5문장 한국어)",
  "candidate_modules": [
    {"module": "후보 모듈/디렉터리/파일명", "rationale": "왜 적용 가치가 있는지 (1-2문장)", "effort": "S|M|L"}
  ],
  "risks": ["예상 리스크 항목 (각 1문장)"],
  "priority": "P0|P1|P2|P3"
}

규칙:
- candidate_modules 는 2-5 개
- risks 는 1-4 개
- 모든 텍스트는 한국어로 작성
- 추측이 과하지 않게, 토픽 키워드와 명확히 연결되는 것만 제안"""


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class ProposalResult:
    proposal_id: str
    cluster_key: str
    diagnosis: Optional[str]
    candidate_modules: list
    risks: list
    priority: Optional[str]
    model: str
    eval_ms: int
    status: str  # generated|failed
    raw_response: Optional[str]


def _build_user_prompt(cluster_summary: dict, hopenvision_context: list[dict]) -> str:
    parts = ["[수집된 기술 토픽]"]
    parts.append(f"키워드: {', '.join(cluster_summary['keywords'])}")
    parts.append(f"이벤트 수: {cluster_summary['event_count']}건 / "
                 f"기간: {cluster_summary['first_seen']} ~ {cluster_summary['last_seen']}")
    parts.append("최근 이벤트 샘플:")
    for ev in cluster_summary["sample_events"][:8]:
        parts.append(f"  - [{ev.get('severity', '?')}] {ev.get('title', '')} "
                     f"(category={ev.get('category')}, service={ev.get('service_tag')})")

    parts.append("")
    parts.append("[HopenVision 최근 30일 활동 (DB workitem)]")
    if hopenvision_context:
        for w in hopenvision_context[:15]:
            parts.append(f"  - [{w['status']}/{w['category']}] {w['title']}")
    else:
        parts.append("  (최근 활동 없음)")

    parts.append("")
    parts.append("위 토픽이 HopenVision 에 어떻게 적용될 수 있을지 JSON 으로 제안하라.")
    return "\n".join(parts)


def _summarize_cluster(cluster) -> dict:
    return {
        "keywords": cluster.keywords,
        "event_count": cluster.event_count,
        "first_seen": cluster.first_seen.strftime("%Y-%m-%d"),
        "last_seen": cluster.last_seen.strftime("%Y-%m-%d"),
        "sample_events": [
            {
                "title": e.title,
                "severity": e.severity,
                "category": e.category,
                "service_tag": e.service_tag,
            }
            for e in cluster.events
        ],
    }


def _fetch_hopenvision_context(session: Session, days: int = 30) -> list[dict]:
    from sqlalchemy import text
    rows = session.execute(text("""
        SELECT title, category, status, updated_at
        FROM work_items
        WHERE github_repo = :repo
          AND updated_at >= NOW() - make_interval(days => :days)
        ORDER BY updated_at DESC
        LIMIT 30
    """), {"repo": HOPENVISION_REPO, "days": days}).mappings().all()
    return [
        {
            "title": r["title"],
            "category": str(r["category"].value) if hasattr(r["category"], "value") else str(r["category"]),
            "status": str(r["status"].value) if hasattr(r["status"], "value") else str(r["status"]),
        }
        for r in rows
    ]


def _parse_llm_json(raw: str) -> Optional[dict]:
    if not raw:
        return None
    # 마크다운 코드블록 제거
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    # 첫 번째 {...} 블록
    m = _JSON_BLOCK_RE.search(cleaned)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        logger.warning("hopenvision: LLM JSON 파싱 실패 — %s", e)
        return None


def generate_proposal(
    session: Session,
    cluster_key: str,
    *,
    cluster_days: int = 30,
    force: bool = False,
) -> ProposalResult:
    """클러스터 → HopenVision 제안 생성. 동일 cluster_key 의 최신 캐시가 있으면 재사용."""
    if not force:
        cached = session.scalars(
            select(HopenVisionProposal)
            .where(HopenVisionProposal.cluster_key == cluster_key,
                   HopenVisionProposal.status == "generated")
            .order_by(HopenVisionProposal.created_at.desc())
            .limit(1)
        ).first()
        if cached:
            return ProposalResult(
                proposal_id=str(cached.id),
                cluster_key=cluster_key,
                diagnosis=cached.diagnosis,
                candidate_modules=cached.candidate_modules or [],
                risks=cached.risks or [],
                priority=cached.priority,
                model=cached.model,
                eval_ms=cached.eval_ms or 0,
                status=cached.status,
                raw_response=cached.raw_response,
            )

    # 클러스터 재조회 — cluster_key 일치하는 것만 사용
    clusters = get_topic_clusters(session, days=cluster_days)
    target = next((c for c in clusters if c.cluster_key == cluster_key), None)
    if target is None:
        raise ValueError(f"cluster_key={cluster_key} 를 현재 클러스터링 결과에서 찾을 수 없습니다")

    cluster_sum = _summarize_cluster(target)
    hopenvision_ctx = _fetch_hopenvision_context(session)

    user_prompt = _build_user_prompt(cluster_sum, hopenvision_ctx)
    model = settings.ollama_model_compose

    gen = chat(
        model=model,
        system=_SYSTEM_PROMPT,
        user=user_prompt,
        temperature=0.2,
        max_tokens=1500,
    )

    parsed = _parse_llm_json(gen.text) if gen.ok else None

    proposal = HopenVisionProposal(
        cluster_key=cluster_key,
        model=model,
        status="generated" if (gen.ok and parsed) else "failed",
        cluster_keywords=target.keywords,
        diagnosis=(parsed or {}).get("diagnosis") if parsed else None,
        candidate_modules=(parsed or {}).get("candidate_modules", []) if parsed else [],
        risks=(parsed or {}).get("risks", []) if parsed else [],
        priority=(parsed or {}).get("priority") if parsed else None,
        raw_response=gen.text,
        eval_ms=gen.eval_duration_ms,
    )
    session.add(proposal)
    session.flush()
    session.commit()

    return ProposalResult(
        proposal_id=str(proposal.id),
        cluster_key=cluster_key,
        diagnosis=proposal.diagnosis,
        candidate_modules=proposal.candidate_modules,
        risks=proposal.risks,
        priority=proposal.priority,
        model=model,
        eval_ms=gen.eval_duration_ms,
        status=proposal.status,
        raw_response=gen.text,
    )


_PRIORITY_MAP = {
    "P0": PlanItemPriority.P0,
    "P1": PlanItemPriority.P1,
    "P2": PlanItemPriority.P2,
    "P3": PlanItemPriority.P3,
}


def accept_as_dev_plan(session: Session, proposal_id: str) -> DevPlan:
    """제안 → DevPlan(DRAFT) + DevPlanItem 자동 초안화."""
    p = session.get(HopenVisionProposal, proposal_id)
    if p is None:
        raise ValueError(f"proposal_id={proposal_id} not found")
    if p.dev_plan_id is not None:
        plan = session.get(DevPlan, p.dev_plan_id)
        if plan:
            return plan

    keywords = ", ".join(p.cluster_keywords[:3]) if p.cluster_keywords else "외부 기술 토픽"
    title = f"[AI 제안] {keywords} 적용 검토"

    overall_priority = _PRIORITY_MAP.get(p.priority or "", PlanItemPriority.P2)
    description = (p.diagnosis or "") + "\n\n[리스크]\n" + "\n".join(
        f"- {r}" for r in (p.risks or [])
    )

    plan = DevPlan(
        project_name=HOPENVISION_PROJECT,
        github_repo="bluevlad/hopenvision",
        title=title,
        description=description.strip() or None,
        status=PlanStatus.DRAFT,
        total_phases=1,
        current_phase=1,
    )
    session.add(plan)
    session.flush()

    for idx, mod in enumerate(p.candidate_modules or []):
        if not isinstance(mod, dict):
            continue
        module_name = (mod.get("module") or "").strip()
        rationale = (mod.get("rationale") or "").strip()
        effort = (mod.get("effort") or "").upper()
        if not module_name:
            continue
        item = DevPlanItem(
            plan_id=plan.id,
            phase=1,
            phase_title="AI 제안 적용 검토",
            sort_order=idx,
            title=module_name[:500],
            description=rationale or None,
            priority=overall_priority,
            status=PlanItemStatus.TODO,
            weight={"S": 0.5, "M": 1.0, "L": 2.0}.get(effort, 1.0),
        )
        session.add(item)

    p.dev_plan_id = plan.id
    p.status = "accepted"
    session.commit()
    return plan


def get_ai_generated_plan_ids(session: Session) -> set[int]:
    """DevPlan 화면에서 'AI 제안' 라벨을 표시할 plan_id 목록."""
    rows = session.execute(
        select(HopenVisionProposal.dev_plan_id)
        .where(HopenVisionProposal.dev_plan_id.is_not(None),
               HopenVisionProposal.status == "accepted")
    ).all()
    return {r[0] for r in rows if r[0] is not None}


# ─────────────────────────────────────────────────────────────────────────
# 기술 토픽 기반 제안 (tech_trend connector + 주간 orchestrator 통합)
# ─────────────────────────────────────────────────────────────────────────

TECH_TOPIC_KEY_PREFIX = "tech:"
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _tech_topic_cluster_key(keyword: str) -> str:
    """기술 토픽 키워드 → cluster_key.

    `cluster_key` 컬럼이 String(40) 으로 짧으므로:
    - 영숫자 외 문자는 `-` 로 정규화하고 32 자로 자른다.
    - 정규화 결과가 너무 짧으면 sha1 hex 8자 fallback.
    """
    base = _SLUG_RE.sub("-", keyword.lower()).strip("-")
    if len(base) < 3:
        base = hashlib.sha1(keyword.encode("utf-8")).hexdigest()[:12]
    base = base[:32]
    return f"{TECH_TOPIC_KEY_PREFIX}{base}"


def _build_tech_topic_summary(topic: "TechTopic") -> dict:
    """TechTopic → cluster summary 와 호환되는 dict (LLM 프롬프트 입력)."""
    sample_events: list[dict] = []
    if topic.digest_title:
        sample_events.append({
            "title": topic.digest_title,
            "severity": (topic.digest_priority or "info"),
            "category": topic.digest_category or "tech_proposal",
            "service_tag": None,
        })
    for art in topic.news_articles:
        sample_events.append({
            "title": art.get("title", ""),
            "severity": "info",
            "category": "tech_news",
            "service_tag": art.get("source"),
        })
    return {
        "keywords": [topic.keyword],
        "event_count": (1 if topic.digest_title else 0) + len(topic.news_articles),
        "first_seen": "—",
        "last_seen": "—",
        "sample_events": sample_events,
        # Medium Digest 의 사전 분석을 LLM 프롬프트에 추가로 전달
        "_extra_context": {
            "digest_summary": topic.digest_summary,
            "digest_target_scope": topic.digest_target_scope,
            "digest_risks": topic.digest_risks,
            "digest_difficulty": topic.digest_difficulty,
            "digest_maturity": topic.digest_maturity,
        },
    }


def _build_tech_topic_user_prompt(
    summary: dict, hopenvision_context: list[dict],
) -> str:
    """tech 토픽 전용 프롬프트 — Medium Digest 의 사전 분석을 hint 로 함께 전달."""
    parts = ["[수집된 기술 토픽]"]
    parts.append(f"키워드: {', '.join(summary['keywords'])}")
    parts.append(f"이벤트 수: {summary['event_count']}건")
    parts.append("최근 이벤트 샘플:")
    for ev in summary["sample_events"][:8]:
        src = f", source={ev.get('service_tag')}" if ev.get('service_tag') else ""
        parts.append(
            f"  - [{ev.get('severity', '?')}] {ev.get('title', '')} "
            f"(category={ev.get('category')}{src})"
        )

    extra = summary.get("_extra_context") or {}
    if any(extra.values()):
        parts.append("")
        parts.append("[Medium Digest 사전 분석 hint]")
        if extra.get("digest_summary"):
            parts.append(f"  설명: {extra['digest_summary']}")
        if extra.get("digest_target_scope"):
            parts.append(f"  적용 대상(예시): {extra['digest_target_scope']}")
        if extra.get("digest_risks"):
            parts.append(f"  리스크(예시): {extra['digest_risks']}")
        if extra.get("digest_difficulty"):
            parts.append(f"  난이도: {extra['digest_difficulty']}")
        if extra.get("digest_maturity"):
            parts.append(f"  성숙도: {extra['digest_maturity']}")

    parts.append("")
    parts.append("[HopenVision 최근 30일 활동 (DB workitem)]")
    if hopenvision_context:
        for w in hopenvision_context[:15]:
            parts.append(f"  - [{w['status']}/{w['category']}] {w['title']}")
    else:
        parts.append("  (최근 활동 없음)")

    parts.append("")
    parts.append(
        "위 토픽이 HopenVision 에 어떻게 적용될 수 있을지 JSON 으로 제안하라. "
        "Medium Digest hint 는 외부 사례 — HopenVision 코드베이스에 맞게 재해석할 것."
    )
    return "\n".join(parts)


def _generate_proposal_for_tech_topic(
    session: Session,
    topic: "TechTopic",
    hopenvision_ctx: list[dict],
    *,
    force: bool,
) -> ProposalResult:
    cluster_key = _tech_topic_cluster_key(topic.keyword)

    if not force:
        cached = session.scalars(
            select(HopenVisionProposal)
            .where(HopenVisionProposal.cluster_key == cluster_key,
                   HopenVisionProposal.status.in_(("generated", "accepted")))
            .order_by(HopenVisionProposal.created_at.desc())
            .limit(1)
        ).first()
        if cached:
            return ProposalResult(
                proposal_id=str(cached.id),
                cluster_key=cluster_key,
                diagnosis=cached.diagnosis,
                candidate_modules=cached.candidate_modules or [],
                risks=cached.risks or [],
                priority=cached.priority,
                model=cached.model,
                eval_ms=cached.eval_ms or 0,
                status=cached.status,
                raw_response=cached.raw_response,
            )

    summary = _build_tech_topic_summary(topic)
    user_prompt = _build_tech_topic_user_prompt(summary, hopenvision_ctx)
    model = settings.ollama_model_compose

    gen = chat(
        model=model,
        system=_SYSTEM_PROMPT,
        user=user_prompt,
        temperature=0.2,
        max_tokens=1500,
    )
    parsed = _parse_llm_json(gen.text) if gen.ok else None

    proposal = HopenVisionProposal(
        cluster_key=cluster_key,
        model=model,
        status="generated" if (gen.ok and parsed) else "failed",
        cluster_keywords=[topic.keyword],
        diagnosis=(parsed or {}).get("diagnosis") if parsed else None,
        candidate_modules=(parsed or {}).get("candidate_modules", []) if parsed else [],
        risks=(parsed or {}).get("risks", []) if parsed else [],
        priority=(parsed or {}).get("priority") if parsed else None,
        raw_response=gen.text,
        eval_ms=gen.eval_duration_ms,
    )
    session.add(proposal)
    session.flush()
    session.commit()

    return ProposalResult(
        proposal_id=str(proposal.id),
        cluster_key=cluster_key,
        diagnosis=proposal.diagnosis,
        candidate_modules=proposal.candidate_modules,
        risks=proposal.risks,
        priority=proposal.priority,
        model=model,
        eval_ms=gen.eval_duration_ms,
        status=proposal.status,
        raw_response=gen.text,
    )


def propose_from_tech_topics(
    session: Session,
    topics: list["TechTopic"],
    *,
    auto_dev_plan: bool = False,
    force: bool = False,
    max_topics: int = 5,
) -> list[ProposalResult]:
    """tech_trend 토픽 묶음 → HopenVision 제안 (+옵션상 DevPlan 초안화).

    Args:
        topics: SynthesisOutput.tech_topics — 키워드 단위로 그룹핑된 토픽
        auto_dev_plan: True 면 generated 직후 `accept_as_dev_plan` 까지 호출 (DevPlan 초안 생성)
        force: 캐시 무시하고 재생성
        max_topics: 1회 호출당 처리할 최대 토픽 수 (LLM 호출 비용 한계)

    Returns:
        ProposalResult 리스트 (max_topics 만큼). 개별 토픽 실패는 흡수.
    """
    if not topics:
        return []

    try:
        hopenvision_ctx = _fetch_hopenvision_context(session)
    except Exception as e:  # noqa: BLE001 — work_items 테이블 없을 수도 있음
        logger.warning("hopenvision context 조회 실패: %s", e)
        hopenvision_ctx = []

    results: list[ProposalResult] = []
    for topic in topics[:max_topics]:
        try:
            result = _generate_proposal_for_tech_topic(
                session, topic, hopenvision_ctx, force=force,
            )
        except Exception as e:  # noqa: BLE001
            logger.error("tech topic 제안 실패 keyword=%s: %s",
                         topic.keyword, e, exc_info=True)
            continue

        if (
            auto_dev_plan
            and result.status == "generated"
            and result.candidate_modules
        ):
            try:
                accept_as_dev_plan(session, result.proposal_id)
                # 상태가 'accepted' 로 바뀌었으므로 result 도 동기화
                result.status = "accepted"
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "tech topic DevPlan 자동 초안화 실패 keyword=%s proposal=%s: %s",
                    topic.keyword, result.proposal_id, e,
                )
        results.append(result)
    return results


def list_tech_topic_proposals(
    session: Session, *, limit: int = 10,
) -> list[HopenVisionProposal]:
    """대시보드용 — tech-trend 출처 제안 최근순."""
    return list(session.scalars(
        select(HopenVisionProposal)
        .where(HopenVisionProposal.cluster_key.like(f"{TECH_TOPIC_KEY_PREFIX}%"))
        .order_by(HopenVisionProposal.created_at.desc())
        .limit(limit)
    ))
