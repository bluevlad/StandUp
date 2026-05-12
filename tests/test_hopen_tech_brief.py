"""hopen_tech_brief orchestrator + sender 채널 단위 테스트 (PR6).

DB / LLM / IngestionHub / 메일 발송은 모킹 — 흐름·축약·렌더링 로직 검증.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.agents_v2.hopen_tech_brief import (
    DailyBriefResult,
    _proposals_to_template_topics,
    _window_range,
    render_hopen_tech_brief,
    run_daily,
)
from app.newsletter.sender import (
    SendSummary,
    list_hopen_tech_recipients,
)
from app.services.hopenvision_proposal_service import ProposalResult
from app.synthesis.pipeline import TechTopic


# ── _window_range ────────────────────────────────────────────────────────

def test_window_range_returns_recent_n_hours():
    since, until = _window_range(24)
    delta = until - since
    assert 23 <= delta.total_seconds() / 3600 <= 25
    # tz-aware
    assert since.tzinfo is not None
    assert until.tzinfo is not None


# ── _proposals_to_template_topics ────────────────────────────────────────

def test_template_topics_skips_filtered_out():
    topics = [TechTopic(keyword="Spring", digest_title="T1", digest_summary="S1")]
    proposals = [
        ProposalResult(
            proposal_id="p1", cluster_key="tech:spring",
            diagnosis="d", candidate_modules=[{"module": "M"}], risks=["r"],
            priority="High", model="m", eval_ms=10, status="generated",
            raw_response="", fitness_score=78, impact_area="backend-api",
            effort_hours=6, diagram_mermaid="flowchart LR\nA-->B",
            case_studies=[{"title": "c1", "url": "https://x"}],
            code_hints=[{"file": "f.java", "change_sketch": "s"}],
        ),
        ProposalResult(
            proposal_id="", cluster_key="tech:unity",
            diagnosis=None, candidate_modules=[], risks=[], priority=None,
            model="", eval_ms=0, status="filtered_out", raw_response=None,
            fitness_score=10, impact_area="unknown",
        ),
    ]
    cards = _proposals_to_template_topics(proposals, topics)
    assert len(cards) == 1
    c = cards[0]
    assert c["keyword"] == "Spring"
    assert c["fitness_score"] == 78
    assert c["impact_area"] == "backend-api"
    assert c["effort_hours"] == 6
    assert "flowchart" in c["diagram_mermaid"]
    assert c["case_studies"][0]["title"] == "c1"
    assert c["code_hints"][0]["file"] == "f.java"
    assert c["priority"] == "high"  # 소문자 정규화


def test_template_topics_invalid_priority_becomes_none():
    topics = [TechTopic(keyword="X")]
    proposals = [
        ProposalResult(
            proposal_id="p1", cluster_key="tech:x",
            diagnosis=None, candidate_modules=[], risks=[], priority="weird",
            model="m", eval_ms=0, status="generated", raw_response=None,
        ),
    ]
    cards = _proposals_to_template_topics(proposals, topics)
    assert cards[0]["priority"] is None


# ── render_hopen_tech_brief ──────────────────────────────────────────────

def test_render_includes_topic_and_counts():
    topics = [TechTopic(keyword="Spring Boot", digest_title="T1", digest_summary="S1")]
    proposals = [
        ProposalResult(
            proposal_id="p1", cluster_key="tech:spring-boot",
            diagnosis="진단", candidate_modules=[{"module": "AdminController"}],
            risks=["r"], priority="high", model="m", eval_ms=0,
            status="generated", raw_response=None,
            fitness_score=78, impact_area="backend-api", effort_hours=4,
            diagram_mermaid="flowchart LR\nA-->B",
            case_studies=[], code_hints=[],
        ),
    ]
    rendered = render_hopen_tech_brief(
        proposals, topics,
        period=date(2026, 5, 12), eligible=1, filtered_out=2,
    )
    assert rendered["subject"].startswith("[HopenTechBrief]")
    assert "2026-05-12" in rendered["subject"]
    assert "Spring Boot" in rendered["subject"]
    assert "통과 1건 / 필터 2건" in rendered["headline"]
    html = rendered["html"]
    assert "AdminController" in html
    assert "flowchart LR" in html
    assert "78" in html  # fitness_score


def test_render_handles_no_topics():
    rendered = render_hopen_tech_brief(
        [], [], period=date(2026, 5, 12),
        eligible=0, filtered_out=0,
    )
    assert "(no topics)" in rendered["subject"]
    assert "통과 0" in rendered["html"] or "임계치" in rendered["html"]


# ── run_daily 통합 (DB·LLM·hub·mail 모킹) ───────────────────────────────

def _fake_event(source_type="medium_digest_report"):
    import uuid
    e = MagicMock()
    e.id = uuid.uuid4()
    e.source_type = source_type
    e.occurred_at = datetime.now(timezone.utc)
    return e


def test_run_daily_skips_send_when_no_eligible_topics(monkeypatch):
    """모든 토픽이 filtered_out 이면 발송 skip + skipped_reason 반환."""
    proposals = [
        ProposalResult(
            proposal_id="", cluster_key="tech:x",
            diagnosis=None, candidate_modules=[], risks=[], priority=None,
            model="", eval_ms=0, status="filtered_out", raw_response=None,
            fitness_score=10, impact_area="unknown",
        ),
    ]
    topics = [TechTopic(keyword="X")]

    fake_hub = MagicMock()
    fake_hub_inst = fake_hub.return_value
    fake_hub_inst.run.return_value = MagicMock(new_events=0, new_chunks=0)

    with patch(
        "app.agents_v2.hopen_tech_brief.IngestionHub", fake_hub,
    ), patch(
        "app.agents_v2.hopen_tech_brief._fetch_recent_tech_events",
        return_value=[_fake_event()],
    ), patch(
        "app.agents_v2.hopen_tech_brief._collect_tech_topics",
        return_value=topics,
    ), patch(
        "app.agents_v2.hopen_tech_brief.propose_from_tech_topics",
        return_value=proposals,
    ), patch(
        "app.agents_v2.hopen_tech_brief.send_hopen_tech_brief",
    ) as mail_mock:
        res = run_daily(dry_run=False)

    assert res.skipped_reason == "no_eligible_topics"
    assert res.eligible == 0
    assert res.filtered_out == 1
    assert res.newsletter_id is None
    mail_mock.assert_not_called()


def test_run_daily_renders_and_sends_when_eligible(monkeypatch, tmp_path):
    """통과 토픽 ≥1 이면 newsletter 저장 + 발송."""
    proposals = [
        ProposalResult(
            proposal_id="p1", cluster_key="tech:spring",
            diagnosis="d", candidate_modules=[{"module": "M"}], risks=[],
            priority="P2", model="m", eval_ms=0,
            status="generated", raw_response=None,
            fitness_score=72, impact_area="backend-api", effort_hours=5,
        ),
    ]
    topics = [TechTopic(keyword="Spring", digest_title="T1", digest_summary="S1")]

    fake_hub = MagicMock()
    fake_hub.return_value.run.return_value = MagicMock(new_events=0, new_chunks=0)

    # SessionLocal 의 instance 가 여러 번 생성되므로 last_nl 을 closure 로 공유
    state = {"last_nl": None}

    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def add(self, obj):
            obj.id = "nl-uuid-1"
            state["last_nl"] = obj
        def commit(self): pass
        def refresh(self, obj): pass
        def get(self, model, oid): return state["last_nl"]

    fake_session_factory = MagicMock(side_effect=lambda: FakeSession())

    send_summary = SendSummary(total=1, success=1, failed=0, failures=[])

    with patch(
        "app.agents_v2.hopen_tech_brief.IngestionHub", fake_hub,
    ), patch(
        "app.agents_v2.hopen_tech_brief.SessionLocal", fake_session_factory,
    ), patch(
        "app.agents_v2.hopen_tech_brief._fetch_recent_tech_events",
        return_value=[_fake_event()],
    ), patch(
        "app.agents_v2.hopen_tech_brief._collect_tech_topics",
        return_value=topics,
    ), patch(
        "app.agents_v2.hopen_tech_brief.propose_from_tech_topics",
        return_value=proposals,
    ), patch(
        "app.agents_v2.hopen_tech_brief.send_hopen_tech_brief",
        return_value=send_summary,
    ) as mail_mock:
        res = run_daily(dry_run=False)

    assert res.eligible == 1
    assert res.filtered_out == 0
    assert res.newsletter_id == "nl-uuid-1"
    assert res.send.success == 1
    mail_mock.assert_called_once()


def test_run_daily_skip_ingest_does_not_call_hub():
    fake_hub = MagicMock()
    with patch(
        "app.agents_v2.hopen_tech_brief.IngestionHub", fake_hub,
    ), patch(
        "app.agents_v2.hopen_tech_brief._fetch_recent_tech_events",
        return_value=[],
    ), patch(
        "app.agents_v2.hopen_tech_brief._collect_tech_topics",
        return_value=[],
    ), patch(
        "app.agents_v2.hopen_tech_brief.propose_from_tech_topics",
        return_value=[],
    ):
        res = run_daily(dry_run=True, skip_ingest=True)

    fake_hub.assert_not_called()
    assert res.eligible == 0
    assert res.skipped_reason == "no_eligible_topics"


# ── sender — hopen_tech 채널 ─────────────────────────────────────────────

def test_list_hopen_tech_recipients_matches_pattern():
    """`report_types` 가 'hopen_tech' / 'all' / 'insight,hopen_tech' 인 활성 사용자만."""
    from app.models.recipient import Recipient

    # SQLAlchemy session.execute 흐름을 모킹
    session = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = ["a@x.com", "b@x.com"]
    session.execute.return_value.scalars.return_value = scalars_mock

    result = list_hopen_tech_recipients(session)
    assert result == ["a@x.com", "b@x.com"]

    # 실제 SQL 호출이 하나 발생했고, WHERE 조건에 'hopen_tech' 또는 'all' 이 포함
    call = session.execute.call_args[0][0]
    compiled = str(call.compile(compile_kwargs={"literal_binds": True}))
    assert "hopen_tech" in compiled
    assert "recipients.is_active" in compiled


# ── weekly 축약 검증 (insight_newsletter 흐름 단편) ─────────────────────

def test_weekly_filters_tech_topics_with_stack_only_gate(monkeypatch):
    """run_weekly 가 호출되면 stack-only 게이트로 syn.tech_topics 축약."""
    from app.agents_v2 import insight_newsletter as agent
    from app.synthesis.pipeline import SynthesisOutput

    # synthesize 가 반환할 가짜 결과
    fake_syn = SynthesisOutput(
        period_start=date(2026, 5, 5), period_end=date(2026, 5, 11),
        headline="h", markdown="# h", kpis={}, analysis={},
        summaries=[], source_event_ids=[], rag_refs=[],
        tech_topics=[
            TechTopic(keyword="Spring", digest_summary="spring boot api"),
            TechTopic(keyword="Unity Engine", digest_summary="game shader"),
        ],
    )

    fake_hub_result = MagicMock(per_connector={}, new_events=0, new_chunks=0)
    fake_send = SendSummary(total=0, success=0, failed=0, failures=[])

    # weekly 흐름에서 외부 효과 모킹
    with patch.object(agent, "IngestionHub") as hub_cls, patch.object(
        agent, "synthesize", return_value=fake_syn,
    ), patch.object(
        agent, "render_newsletter",
        return_value={"subject": "S", "headline": "H",
                       "html": "<p>x</p>", "plain_summary": "p"},
    ), patch.object(
        agent, "SessionLocal",
    ) as session_cls, patch.object(
        agent, "send_newsletter", return_value=fake_send,
    ), patch.object(
        agent, "index_newsletter", return_value=0,
    ), patch.object(
        agent.settings, "tech_trend_auto_dev_plan", False,
    ), patch.object(
        agent.settings, "weekly_tech_stack_min_score", 25,
    ), patch.object(
        agent.settings, "hopenvision_stack_tags",
        "java,spring,react,postgresql,typescript",
    ):
        hub_cls.return_value.run.return_value = fake_hub_result
        # SessionLocal() 컨텍스트
        sess = MagicMock()
        sess.__enter__.return_value = sess
        sess.__exit__.return_value = False
        sess.add = MagicMock()
        sess.commit = MagicMock()
        nl_obj = MagicMock()
        nl_obj.id = "nl-id-1"
        sess.refresh.side_effect = lambda obj: setattr(obj, "id", "nl-id-1")
        sess.get.return_value = nl_obj
        session_cls.return_value = sess

        result = agent.run_weekly(dry_run=True)

    # Spring 만 남고 Unity 는 컷
    keywords = [t.keyword for t in result.synthesis.tech_topics]
    assert keywords == ["Spring"]
