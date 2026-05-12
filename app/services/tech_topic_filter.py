"""HopenVision 적합도 필터 (PR4).

`TechTopic` 1건을 받아 HopenVision 코드베이스에 적용 가능한지를 0~100 점으로
평가한다. 두 신호를 합산:

1. **스택 태그 결정적 매칭 (0~60점)** — 키워드·디지스트 요약·뉴스 제목에서
   `HOPENVISION_STACK_TAGS` 가 몇 개 발견되는지. 가중치 부여 후 60 cap.
2. **LLM 1-shot 분류 (0~40점)** — repo index 요약과 토픽 요약을 보고
   `{score_extra, impact_area, effort_hours, reason}` JSON 으로 응답.
   LLM 실패 시 0점.

`score >= HOPEN_BRIEF_FITNESS_THRESHOLD` 면 `eligible=True`.
연동: `hopenvision_proposal_service.propose_from_tech_topics` 가 호출.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from ..core.config import settings
from ..synthesis.ollama_client import chat
from .hopenvision_repo_indexer import condense_for_prompt

if TYPE_CHECKING:
    from ..synthesis.pipeline import TechTopic

logger = logging.getLogger(__name__)

_VALID_IMPACT_AREAS = {
    "backend-api", "frontend-admin", "frontend-user",
    "shared", "infra", "data", "unknown",
}

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

_LLM_SYSTEM_PROMPT = """당신은 HopenVision (Java Spring Boot 합격예측 시스템 + React
TypeScript 프론트엔드) 의 시니어 엔지니어다.

주어진 외부 기술 토픽이 HopenVision 코드베이스에 *얼마나 직접 적용 가능한지* 판단해
JSON 으로만 응답한다. 다른 텍스트나 마크다운 코드블록 없이 순수 JSON.

스키마:
{
  "score_extra": 0~40 정수,
  "impact_area": "backend-api|frontend-admin|frontend-user|shared|infra|data|unknown",
  "effort_hours": 1~80 정수 (예상 도입 공수),
  "reason": "1-2문장 한국어 — 왜 적용 가능/불가능한지"
}

채점 가이드:
- 40 = repo 의 특정 모듈/엔티티/페이지에 *직접* 매핑됨, 의존성 추가만으로 도입 가능
- 25 = 분야는 일치하나 의존성·리팩토링 부담 큼
- 10 = 컨셉만 유사 (영감 수준)
- 0  = HopenVision 과 무관한 영역 (예: 머신러닝 비전, 게임, 데스크톱 앱 등)"""


@dataclass
class FitnessResult:
    score: int                          # 0~100
    eligible: bool
    matched_stack_tags: list[str]       # 발견된 스택 태그 (정규화 소문자)
    impact_area: str                    # _VALID_IMPACT_AREAS 중 하나
    effort_hours: Optional[int]
    reason: str
    stack_score: int                    # 0~60
    llm_score: int                      # 0~40
    model: str                          # LLM 모델명 (호출 안한 경우 "")
    eval_ms: int = 0
    extra: dict = field(default_factory=dict)


def _stack_tags() -> list[str]:
    raw = (settings.hopenvision_stack_tags or "").lower()
    return [t.strip() for t in raw.split(",") if t.strip()]


def _topic_text_blob(topic: "TechTopic") -> str:
    """토픽의 모든 텍스트를 합쳐 소문자로 — 스택 매칭용."""
    parts: list[str] = [topic.keyword]
    if topic.digest_title:
        parts.append(topic.digest_title)
    if topic.digest_summary:
        parts.append(topic.digest_summary)
    if topic.digest_target_scope:
        parts.append(topic.digest_target_scope)
    if topic.digest_category:
        parts.append(topic.digest_category)
    for art in topic.news_articles[:5]:
        parts.append(art.get("title", ""))
        parts.append(art.get("description", ""))
    return " \n".join(p for p in parts if p).lower()


def _score_stack_match(text: str, stack_tags: list[str]) -> tuple[int, list[str]]:
    """발견된 스택 태그 수에 따라 점수 산출 (0~60).

    - 1개 매칭: 25
    - 2개:     40
    - 3개:     50
    - 4개 이상: 60

    같은 태그의 다중 등장은 1회로 카운트. 정확한 단어 경계 매칭으로 false positive 감소.
    """
    found: list[str] = []
    for tag in stack_tags:
        # 태그가 '-' 포함하면 그대로 substring 매칭 (예: spring-boot), 그 외엔 \b 경계
        if "-" in tag or "." in tag:
            if tag in text:
                found.append(tag)
        else:
            if re.search(rf"\b{re.escape(tag)}\b", text):
                found.append(tag)

    n = len(found)
    if n == 0:
        score = 0
    elif n == 1:
        score = 25
    elif n == 2:
        score = 40
    elif n == 3:
        score = 50
    else:
        score = 60
    return score, found


def _build_llm_prompt(topic: "TechTopic", repo_summary: str) -> str:
    parts = ["[외부 기술 토픽]"]
    parts.append(f"키워드: {topic.keyword}")
    if topic.digest_title:
        parts.append(f"디지스트 제목: {topic.digest_title}")
    if topic.digest_summary:
        parts.append(f"설명: {topic.digest_summary[:400]}")
    if topic.digest_target_scope:
        parts.append(f"적용 대상(외부 예시): {topic.digest_target_scope[:300]}")
    if topic.digest_category:
        parts.append(f"카테고리: {topic.digest_category}")
    # PR-SU-11 — medium-digest-agent 가 제공하는 한국어 의미 해석을 LLM 컨텍스트로 첨부.
    # 영어 제목을 가공한 결과라 게이트 LLM 이 적합성 판단을 정확히 한다.
    if topic.interpretation_core:
        parts.append(f"핵심 메시지: {topic.interpretation_core}")
    if topic.interpretation_why:
        parts.append(f"왜 화제: {topic.interpretation_why}")
    if topic.interpretation_takeaways:
        parts.append("Take-away: " + " / ".join(topic.interpretation_takeaways[:3]))
    if topic.importance_score is not None:
        parts.append(f"외부 중요도(0~100): {topic.importance_score}")
    if topic.news_articles:
        parts.append("관련 뉴스:")
        for art in topic.news_articles[:3]:
            parts.append(f"  - {art.get('title', '')}")

    parts.append("")
    parts.append(repo_summary)
    parts.append("")
    parts.append(
        "위 토픽이 HopenVision 에 얼마나 직접 적용 가능한지 평가하여 JSON 으로 응답하라. "
        "추측 금지 — repo index 에 명시된 모듈/엔티티/페이지 와 연결 가능한 것만 높게 평가."
    )
    return "\n".join(parts)


def _parse_llm_json(raw: str) -> Optional[dict]:
    if not raw:
        return None
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    m = _JSON_BLOCK_RE.search(cleaned)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        logger.warning("fitness LLM JSON 파싱 실패: %s", e)
        return None


def _normalize_impact_area(raw: str) -> str:
    if not raw:
        return "unknown"
    s = raw.strip().lower()
    return s if s in _VALID_IMPACT_AREAS else "unknown"


def _clamp(v, lo, hi):
    try:
        x = int(v)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, x))


def evaluate_topic(
    topic: "TechTopic",
    repo_index: Optional[dict] = None,
    *,
    use_llm: bool = True,
    threshold: Optional[int] = None,
) -> FitnessResult:
    """단일 토픽의 HopenVision 적합도 평가."""
    th = threshold if threshold is not None else settings.hopen_brief_fitness_threshold
    stack_tags = _stack_tags()
    blob = _topic_text_blob(topic)
    stack_score, matched = _score_stack_match(blob, stack_tags)

    # LLM 호출 — 스택 점수가 0 이면 어차피 의미 없으니 스킵해 비용 절약
    llm_score = 0
    impact_area = "unknown"
    effort_hours: Optional[int] = None
    reason = ""
    model = ""
    eval_ms = 0
    extra: dict = {}

    if use_llm and stack_score > 0:
        repo_summary = condense_for_prompt(repo_index or {})
        prompt = _build_llm_prompt(topic, repo_summary)
        gen = chat(
            model=settings.ollama_model_analyze,
            system=_LLM_SYSTEM_PROMPT,
            user=prompt,
            temperature=0.1,
            max_tokens=400,
        )
        model = settings.ollama_model_analyze
        eval_ms = gen.eval_duration_ms

        parsed = _parse_llm_json(gen.text) if gen.ok else None
        if parsed:
            llm_score = _clamp(parsed.get("score_extra"), 0, 40)
            impact_area = _normalize_impact_area(parsed.get("impact_area", ""))
            effort_hours = _clamp(parsed.get("effort_hours"), 1, 80) \
                if parsed.get("effort_hours") is not None else None
            reason = str(parsed.get("reason", ""))[:400]
        else:
            extra["llm_raw"] = (gen.text or "")[:400]
            extra["llm_ok"] = gen.ok

    total = min(100, stack_score + llm_score)
    return FitnessResult(
        score=total,
        eligible=total >= th,
        matched_stack_tags=matched,
        impact_area=impact_area,
        effort_hours=effort_hours,
        reason=reason,
        stack_score=stack_score,
        llm_score=llm_score,
        model=model,
        eval_ms=eval_ms,
        extra=extra,
    )
