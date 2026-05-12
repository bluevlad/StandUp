"""tech-trend → HopenVision 제안 어댑터 단위 테스트.

DB/LLM 외부 의존은 모킹.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.hopenvision_proposal_service import (
    TECH_TOPIC_KEY_PREFIX,
    _build_tech_topic_summary,
    _build_tech_topic_user_prompt,
    _tech_topic_cluster_key,
    propose_from_tech_topics,
)
from app.synthesis.pipeline import TechTopic


# ── _tech_topic_cluster_key ──────────────────────────────────────────────
def test_cluster_key_normalizes_keyword():
    assert _tech_topic_cluster_key("Java 21+") == "tech:java-21"
    assert _tech_topic_cluster_key("React 19").startswith("tech:react-19")


def test_cluster_key_truncates_to_40_chars_total():
    huge = "Spring " * 20
    key = _tech_topic_cluster_key(huge)
    assert key.startswith(TECH_TOPIC_KEY_PREFIX)
    assert len(key) <= 40


def test_cluster_key_falls_back_to_hash_when_normalized_too_short():
    # 한글만 있어 정규식이 모두 떨궈내는 경우 해시 fallback
    key = _tech_topic_cluster_key("자바")
    assert key.startswith(TECH_TOPIC_KEY_PREFIX)
    assert len(key) > len(TECH_TOPIC_KEY_PREFIX) + 3


def test_cluster_key_stable_for_same_keyword():
    a = _tech_topic_cluster_key("Java 21")
    b = _tech_topic_cluster_key("Java 21")
    assert a == b


# ── _build_tech_topic_summary ────────────────────────────────────────────
def test_summary_counts_digest_and_news_events():
    topic = TechTopic(
        keyword="Java",
        digest_title="[Java] 적용 제안",
        digest_priority="high",
        digest_summary="설명",
        news_articles=[
            {"title": "n1", "url": "u1", "source": "google",
             "description": "", "published_at": ""},
            {"title": "n2", "url": "u2", "source": "naver",
             "description": "", "published_at": ""},
        ],
    )
    s = _build_tech_topic_summary(topic)
    assert s["keywords"] == ["Java"]
    assert s["event_count"] == 3
    titles = [e["title"] for e in s["sample_events"]]
    assert "[Java] 적용 제안" in titles
    assert "n1" in titles and "n2" in titles
    assert s["_extra_context"]["digest_summary"] == "설명"


def test_summary_handles_news_only_topic():
    topic = TechTopic(
        keyword="React",
        news_articles=[
            {"title": "r1", "url": "", "source": "google",
             "description": "", "published_at": ""},
        ],
    )
    s = _build_tech_topic_summary(topic)
    assert s["event_count"] == 1
    # digest 없음 — sample_events 에 첫 항목이 news 여야 함
    assert s["sample_events"][0]["title"] == "r1"


# ── _build_tech_topic_user_prompt ────────────────────────────────────────
def test_user_prompt_includes_digest_hint_and_hopenvision_context():
    summary = {
        "keywords": ["Java"],
        "event_count": 2,
        "sample_events": [
            {"title": "T1", "severity": "high",
             "category": "language-features", "service_tag": None},
        ],
        "_extra_context": {
            "digest_summary": "Java 설명",
            "digest_target_scope": "신규 모듈",
            "digest_risks": "호환성",
            "digest_difficulty": "medium",
            "digest_maturity": "mainstream",
        },
    }
    ctx = [{"title": "기존 작업", "category": "feature", "status": "in_progress"}]
    prompt = _build_tech_topic_user_prompt(summary, ctx)
    assert "Java" in prompt
    assert "T1" in prompt
    assert "Java 설명" in prompt
    assert "신규 모듈" in prompt
    assert "기존 작업" in prompt
    assert "JSON" in prompt


def test_user_prompt_when_no_hint_omits_hint_block():
    summary = {
        "keywords": ["X"], "event_count": 1,
        "sample_events": [{"title": "t", "severity": "info",
                           "category": "tech_news", "service_tag": "google"}],
        "_extra_context": {
            "digest_summary": "", "digest_target_scope": "",
            "digest_risks": "", "digest_difficulty": "",
            "digest_maturity": "",
        },
    }
    prompt = _build_tech_topic_user_prompt(summary, [])
    assert "Medium Digest 사전 분석 hint" not in prompt
    assert "(최근 활동 없음)" in prompt


# ── propose_from_tech_topics 통합 (mock) ────────────────────────────────
def _fake_chat_result(text: str, ok: bool = True):
    res = MagicMock()
    res.ok = ok
    res.text = text
    res.eval_duration_ms = 123
    res.error = None if ok else "boom"
    return res


# ── 기존 (PR3) 테스트들 — fitness 게이트는 _GATE_OFF 로 비활성화해서 본래 의도만 검증
# PR4 게이트 동작은 별도 테스트(test_propose_*_gate_*) 에서 검증
_GATE_OFF = {"fitness_threshold": 0, "use_llm_fitness": False}


def test_propose_from_tech_topics_skips_when_empty():
    session = MagicMock()
    out = propose_from_tech_topics(session, [], auto_dev_plan=False, **_GATE_OFF)
    assert out == []
    session.add.assert_not_called()


def test_propose_from_tech_topics_generates_per_topic():
    topics = [
        TechTopic(keyword="Java"),
        TechTopic(keyword="React"),
    ]
    session = MagicMock()
    # 캐시 없음
    session.scalars.return_value.first.return_value = None

    fake_response = '{"diagnosis":"d","candidate_modules":[{"module":"m","rationale":"r","effort":"M"}],"risks":["risk1"],"priority":"P2"}'

    with patch(
        "app.services.hopenvision_proposal_service._fetch_hopenvision_context",
        return_value=[],
    ), patch(
        "app.services.hopenvision_proposal_service.chat",
        return_value=_fake_chat_result(fake_response),
    ):
        results = propose_from_tech_topics(
            session, topics, auto_dev_plan=False, max_topics=5, **_GATE_OFF,
        )

    assert len(results) == 2
    for r in results:
        assert r.status == "generated"
        assert r.diagnosis == "d"
        assert r.priority == "P2"
        assert r.candidate_modules and r.candidate_modules[0]["module"] == "m"
    # 토픽 수만큼 add 호출
    assert session.add.call_count == 2


def test_propose_from_tech_topics_respects_max_topics():
    topics = [TechTopic(keyword=f"kw{i}") for i in range(10)]
    session = MagicMock()
    session.scalars.return_value.first.return_value = None
    fake_response = '{"diagnosis":"d","candidate_modules":[],"risks":[],"priority":"P3"}'

    with patch(
        "app.services.hopenvision_proposal_service._fetch_hopenvision_context",
        return_value=[],
    ), patch(
        "app.services.hopenvision_proposal_service.chat",
        return_value=_fake_chat_result(fake_response),
    ):
        results = propose_from_tech_topics(
            session, topics, auto_dev_plan=False, max_topics=2, **_GATE_OFF,
        )

    assert len(results) == 2


def test_propose_from_tech_topics_uses_cache_when_not_force():
    topics = [TechTopic(keyword="Java")]
    session = MagicMock()
    cached = MagicMock()
    cached.id = "cached-id"
    cached.diagnosis = "cached d"
    cached.candidate_modules = [{"module": "cm"}]
    cached.risks = ["cr"]
    cached.priority = "P1"
    cached.model = "exaone3.5:7.8b"
    cached.eval_ms = 50
    cached.status = "generated"
    cached.raw_response = "raw"
    cached.fitness_score = 80
    cached.impact_area = "backend-api"
    cached.effort_hours = 6
    session.scalars.return_value.first.return_value = cached

    with patch(
        "app.services.hopenvision_proposal_service._fetch_hopenvision_context",
        return_value=[],
    ), patch(
        "app.services.hopenvision_proposal_service.chat",
    ) as chat_mock:
        results = propose_from_tech_topics(
            session, topics, auto_dev_plan=False, force=False, **_GATE_OFF,
        )

    chat_mock.assert_not_called()
    assert len(results) == 1
    assert results[0].diagnosis == "cached d"
    # add 도 호출 안 됨 (캐시 재사용)
    session.add.assert_not_called()


def test_propose_from_tech_topics_auto_dev_plan_invokes_acceptor():
    topics = [TechTopic(keyword="Java")]
    session = MagicMock()
    session.scalars.return_value.first.return_value = None
    fake_response = '{"diagnosis":"d","candidate_modules":[{"module":"M","effort":"S"}],"risks":[],"priority":"P2"}'

    with patch(
        "app.services.hopenvision_proposal_service._fetch_hopenvision_context",
        return_value=[],
    ), patch(
        "app.services.hopenvision_proposal_service.chat",
        return_value=_fake_chat_result(fake_response),
    ), patch(
        "app.services.hopenvision_proposal_service.accept_as_dev_plan",
    ) as accept_mock:
        results = propose_from_tech_topics(
            session, topics, auto_dev_plan=True, **_GATE_OFF,
        )

    assert accept_mock.call_count == 1
    assert results[0].status == "accepted"


def test_propose_from_tech_topics_skips_dev_plan_when_no_modules():
    """candidate_modules 가 비어있으면 DevPlan 생성 자체가 의미 없으므로 호출 X."""
    topics = [TechTopic(keyword="Java")]
    session = MagicMock()
    session.scalars.return_value.first.return_value = None
    fake_response = '{"diagnosis":"d","candidate_modules":[],"risks":["r"],"priority":"P3"}'

    with patch(
        "app.services.hopenvision_proposal_service._fetch_hopenvision_context",
        return_value=[],
    ), patch(
        "app.services.hopenvision_proposal_service.chat",
        return_value=_fake_chat_result(fake_response),
    ), patch(
        "app.services.hopenvision_proposal_service.accept_as_dev_plan",
    ) as accept_mock:
        propose_from_tech_topics(session, topics, auto_dev_plan=True, **_GATE_OFF)

    accept_mock.assert_not_called()


def test_propose_from_tech_topics_handles_llm_failure():
    """LLM 호출 실패 시 'failed' status 로 저장되고 auto_dev_plan 도 안 호출."""
    topics = [TechTopic(keyword="Java")]
    session = MagicMock()
    session.scalars.return_value.first.return_value = None

    with patch(
        "app.services.hopenvision_proposal_service._fetch_hopenvision_context",
        return_value=[],
    ), patch(
        "app.services.hopenvision_proposal_service.chat",
        return_value=_fake_chat_result("garbage", ok=False),
    ), patch(
        "app.services.hopenvision_proposal_service.accept_as_dev_plan",
    ) as accept_mock:
        results = propose_from_tech_topics(
            session, topics, auto_dev_plan=True, **_GATE_OFF,
        )

    assert results[0].status == "failed"
    accept_mock.assert_not_called()


# ── PR4: HopenVision 적합도 게이트 ────────────────────────────────────────

def test_propose_filters_out_below_threshold():
    """fitness_score < threshold 면 LLM 호출 없이 filtered_out 으로 반환."""
    topics = [TechTopic(keyword="Java"), TechTopic(keyword="Unity Engine")]
    session = MagicMock()

    from app.services.tech_topic_filter import FitnessResult

    def fake_eval(topic, repo_index, **kw):
        if topic.keyword == "Java":
            return FitnessResult(
                score=80, eligible=True, matched_stack_tags=["java"],
                impact_area="backend-api", effort_hours=4, reason="ok",
                stack_score=40, llm_score=40, model="m", eval_ms=10,
            )
        return FitnessResult(
            score=10, eligible=False, matched_stack_tags=[],
            impact_area="unknown", effort_hours=None, reason="무관",
            stack_score=10, llm_score=0, model="m", eval_ms=5,
        )

    session.scalars.return_value.first.return_value = None
    fake_response = '{"diagnosis":"d","candidate_modules":[],"risks":[],"priority":"P3"}'

    with patch(
        "app.services.hopenvision_proposal_service._fetch_hopenvision_context",
        return_value=[],
    ), patch(
        "app.services.hopenvision_proposal_service.index_hopenvision_repo",
        return_value={"summary": {}},
    ), patch(
        "app.services.hopenvision_proposal_service.evaluate_topic",
        side_effect=fake_eval,
    ), patch(
        "app.services.hopenvision_proposal_service.chat",
        return_value=_fake_chat_result(fake_response),
    ) as chat_mock:
        results = propose_from_tech_topics(
            session, topics, auto_dev_plan=False, fitness_threshold=60,
        )

    # Java 만 LLM 호출
    assert chat_mock.call_count == 1
    # 결과는 2개 모두 반환되지만 상태가 다름
    statuses = [r.status for r in results]
    assert "filtered_out" in statuses
    assert "generated" in statuses
    filtered = next(r for r in results if r.status == "filtered_out")
    assert filtered.fitness_score == 10
    assert filtered.impact_area == "unknown"
    assert filtered.proposal_id == ""  # DB 저장 안 됨


def test_propose_persists_fitness_fields_on_generated():
    """통과 토픽은 ProposalResult.fitness_* 가 채워져야 함."""
    topics = [TechTopic(keyword="Spring Boot")]
    session = MagicMock()
    session.scalars.return_value.first.return_value = None

    from app.services.tech_topic_filter import FitnessResult

    fit = FitnessResult(
        score=75, eligible=True, matched_stack_tags=["spring-boot"],
        impact_area="backend-api", effort_hours=12, reason="컨트롤러 매핑",
        stack_score=25, llm_score=50, model="m", eval_ms=20,
    )
    fake_response = '{"diagnosis":"d","candidate_modules":[{"module":"M","effort":"M"}],"risks":[],"priority":"P1"}'

    with patch(
        "app.services.hopenvision_proposal_service._fetch_hopenvision_context",
        return_value=[],
    ), patch(
        "app.services.hopenvision_proposal_service.index_hopenvision_repo",
        return_value={"summary": {"controllers": 1}},
    ), patch(
        "app.services.hopenvision_proposal_service.evaluate_topic",
        return_value=fit,
    ), patch(
        "app.services.hopenvision_proposal_service.chat",
        return_value=_fake_chat_result(fake_response),
    ):
        results = propose_from_tech_topics(
            session, topics, auto_dev_plan=False, fitness_threshold=60,
        )

    assert len(results) == 1
    r = results[0]
    assert r.status == "generated"
    assert r.fitness_score == 75
    assert r.impact_area == "backend-api"
    assert r.effort_hours == 12
    assert r.fitness_reason == "컨트롤러 매핑"
