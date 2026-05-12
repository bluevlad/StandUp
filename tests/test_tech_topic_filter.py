"""tech_topic_filter 단위 테스트 (PR4)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.tech_topic_filter import (
    FitnessResult,
    _score_stack_match,
    _stack_tags,
    evaluate_topic,
)
from app.synthesis.ollama_client import GenResult
from app.synthesis.pipeline import TechTopic


def _mk_gen_ok(text: str) -> GenResult:
    return GenResult(text=text, model="m", eval_count=1, eval_duration_ms=10, ok=True)


def _mk_gen_fail() -> GenResult:
    return GenResult(text="", model="m", eval_count=0, eval_duration_ms=0, ok=False,
                     error="boom")


# ── stack 매칭 산출식 ─────────────────────────────────────────────────────

def test_stack_match_zero_when_nothing_found():
    score, found = _score_stack_match("no relevant text here", ["java", "react"])
    assert score == 0
    assert found == []


def test_stack_match_word_boundary():
    # "javascript" 는 \bjava\b 에 매칭되면 안 됨
    score, found = _score_stack_match("learning javascript today", ["java"])
    assert score == 0
    assert "java" not in found


def test_stack_match_hyphen_tag_substring():
    score, found = _score_stack_match(
        "we use spring-boot 3.4 in production", ["spring-boot"],
    )
    assert score == 25
    assert "spring-boot" in found


def test_stack_match_scales_with_count():
    text = "spring boot react java postgresql typescript"
    # 5개 매칭 → cap 60
    tags = ["java", "spring", "react", "postgresql", "typescript"]
    score, found = _score_stack_match(text, tags)
    assert score == 60
    assert len(found) == 5


# ── evaluate_topic 통합 (LLM 모킹) ───────────────────────────────────────

def _topic(keyword="Spring Boot", summary="Spring Boot 3 새 기능", news=()):
    return TechTopic(
        keyword=keyword,
        digest_title=f"[{keyword}] 적용 제안",
        digest_summary=summary,
        digest_target_scope="API 계층",
        digest_category="framework",
        news_articles=list(news),
    )


def test_evaluate_eligible_when_score_meets_threshold(monkeypatch):
    """스택 매칭 1개(25점) + LLM 40점 → 65점 → threshold 60 통과."""
    monkeypatch.setattr(
        "app.services.tech_topic_filter.settings.hopenvision_stack_tags",
        "java,spring,spring-boot,react",
    )
    monkeypatch.setattr(
        "app.services.tech_topic_filter.settings.hopen_brief_fitness_threshold", 60,
    )
    monkeypatch.setattr(
        "app.services.tech_topic_filter.settings.ollama_model_analyze", "fake-model",
    )

    llm_resp = (
        '{"score_extra": 40, "impact_area": "backend-api", '
        '"effort_hours": 8, "reason": "AuthController 와 직접 매핑"}'
    )
    with patch(
        "app.services.tech_topic_filter.chat", return_value=_mk_gen_ok(llm_resp),
    ):
        result = evaluate_topic(
            _topic("Spring"),  # stack match: "spring" → 25
            repo_index={"summary": {"controllers": 1}},
        )

    assert isinstance(result, FitnessResult)
    assert result.stack_score == 25
    assert result.llm_score == 40
    assert result.score == 65
    assert result.eligible is True
    assert result.impact_area == "backend-api"
    assert result.effort_hours == 8
    assert "AuthController" in result.reason
    assert "spring" in result.matched_stack_tags


def test_evaluate_skips_llm_when_stack_zero(monkeypatch):
    """무관 토픽 — LLM 호출조차 하지 않음."""
    monkeypatch.setattr(
        "app.services.tech_topic_filter.settings.hopenvision_stack_tags",
        "java,spring,react",
    )
    monkeypatch.setattr(
        "app.services.tech_topic_filter.settings.hopen_brief_fitness_threshold", 60,
    )

    with patch("app.services.tech_topic_filter.chat") as mocked_chat:
        result = evaluate_topic(
            _topic("Unity Engine", summary="게임 엔진 셰이더 튜닝"),
        )
        assert not mocked_chat.called
    assert result.stack_score == 0
    assert result.llm_score == 0
    assert result.score == 0
    assert result.eligible is False


def test_evaluate_llm_failure_falls_back_to_stack_only(monkeypatch):
    monkeypatch.setattr(
        "app.services.tech_topic_filter.settings.hopenvision_stack_tags",
        "java,spring,react,postgresql,typescript",
    )
    # threshold 보수적으로 50 → 스택 50점만으로도 통과
    monkeypatch.setattr(
        "app.services.tech_topic_filter.settings.hopen_brief_fitness_threshold", 50,
    )
    with patch(
        "app.services.tech_topic_filter.chat", return_value=_mk_gen_fail(),
    ):
        result = evaluate_topic(
            _topic("React", summary="React Server Components + TypeScript + PostgreSQL"),
        )
    assert result.stack_score >= 50  # 3개 이상 매칭
    assert result.llm_score == 0
    assert result.eligible is True
    assert "llm_ok" in result.extra


def test_evaluate_invalid_impact_area_normalized_to_unknown(monkeypatch):
    monkeypatch.setattr(
        "app.services.tech_topic_filter.settings.hopenvision_stack_tags", "java",
    )
    monkeypatch.setattr(
        "app.services.tech_topic_filter.settings.hopen_brief_fitness_threshold", 99,
    )
    llm_resp = (
        '{"score_extra": 10, "impact_area": "mobile-ios", '
        '"effort_hours": 4, "reason": "x"}'
    )
    with patch(
        "app.services.tech_topic_filter.chat", return_value=_mk_gen_ok(llm_resp),
    ):
        result = evaluate_topic(_topic("Java"))
    assert result.impact_area == "unknown"
    assert result.eligible is False  # threshold 99


def test_evaluate_use_llm_false_skips_llm(monkeypatch):
    """테스트·CI 환경에서 LLM 끄고 스택만으로 확인 가능."""
    monkeypatch.setattr(
        "app.services.tech_topic_filter.settings.hopenvision_stack_tags",
        "java,spring",
    )
    with patch("app.services.tech_topic_filter.chat") as mocked_chat:
        result = evaluate_topic(_topic("Java"), use_llm=False, threshold=20)
        assert not mocked_chat.called
    assert result.score == result.stack_score
    assert result.llm_score == 0
