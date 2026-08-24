"""기술 토픽 합성/렌더링 단위 테스트.

- _collect_tech_topics: digest + news 이벤트 그룹핑 로직
- _build_tech_topic_items: builder 변환
- 템플릿 렌더링: jinja 가 tech_topics 블록을 정상 처리하는지
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from app.models.insight import (
    SOURCE_LOGANALYZER,
    SOURCE_MEDIUM_DIGEST_REPORT,
    SOURCE_TECH_NEWS_ARTICLE,
)
from app.newsletter.builder import _build_tech_topic_items, render_newsletter
from app.synthesis.pipeline import (
    SynthesisOutput,
    TechTopic,
    _collect_tech_topics,
)


@dataclass
class FakeEvent:
    """IngestionEvent ORM 의 duck-type — 합성 단계에서 쓰는 필드만 흉내."""
    id: str
    source_type: str
    title: str
    occurred_at: datetime
    canonical: dict[str, Any] = field(default_factory=dict)
    source_url: str | None = None
    service_tag: str | None = None
    severity: str | None = None
    category: str | None = None
    raw_excerpt: str | None = None


def _digest_event(
    *, keyword: str, title: str, priority: str = "",
    occurred_at: datetime | None = None, event_id: str = "d1",
    tech_description: str = "tech desc", target_scope: str = "scope",
    risks: str = "risk text",
) -> FakeEvent:
    return FakeEvent(
        id=event_id,
        source_type=SOURCE_MEDIUM_DIGEST_REPORT,
        title=title,
        occurred_at=occurred_at or datetime(2026, 4, 13, tzinfo=timezone.utc),
        canonical={
            "keyword": keyword,
            "priority": priority,
            "category": "language-features",
            "difficulty": "medium",
            "maturity": "mainstream",
            "tech_description": tech_description,
            "target_scope": target_scope,
            "risks": risks,
        },
        source_url="file:///tmp/x.md",
    )


def _news_event(
    *, keyword: str, title: str, source: str = "google",
    occurred_at: datetime | None = None, event_id: str = "n1",
) -> FakeEvent:
    return FakeEvent(
        id=event_id,
        source_type=SOURCE_TECH_NEWS_ARTICLE,
        title=title,
        occurred_at=occurred_at or datetime(2026, 4, 13, 12, tzinfo=timezone.utc),
        canonical={
            "keyword": keyword,
            "source": source,
            "description": "news description",
        },
        source_url=f"https://news.example.com/{event_id}",
    )


# ── _collect_tech_topics ─────────────────────────────────────────────────
def test_collect_tech_topics_groups_by_keyword():
    events = [
        _digest_event(keyword="Java 21", title="[Java 21] 적용", event_id="dj"),
        _news_event(keyword="Java 21", title="Java 21 release", event_id="n1"),
        _news_event(keyword="Java 21", title="Pattern matching", event_id="n2"),
        _digest_event(keyword="React 19", title="[React 19] 적용",
                      priority="high", event_id="dr"),
    ]
    topics = _collect_tech_topics(events)
    by_kw = {t.keyword: t for t in topics}
    assert set(by_kw.keys()) == {"Java 21", "React 19"}
    assert len(by_kw["Java 21"].news_articles) == 2
    assert len(by_kw["React 19"].news_articles) == 0


def test_collect_tech_topics_picks_latest_digest_per_keyword():
    older = _digest_event(
        keyword="Java",
        title="old digest",
        occurred_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        event_id="old",
    )
    newer = _digest_event(
        keyword="Java",
        title="new digest",
        occurred_at=datetime(2026, 4, 13, tzinfo=timezone.utc),
        event_id="new",
    )
    topics = _collect_tech_topics([older, newer])
    assert len(topics) == 1
    assert topics[0].digest_title == "new digest"
    assert topics[0].digest_event_id == "new"


def test_collect_tech_topics_news_only_keyword_kept():
    events = [
        _news_event(keyword="Spring Boot", title="Spring article 1"),
    ]
    topics = _collect_tech_topics(events)
    assert len(topics) == 1
    assert topics[0].keyword == "Spring Boot"
    assert topics[0].digest_title == ""
    assert len(topics[0].news_articles) == 1


def test_collect_tech_topics_orders_by_priority_then_digest_then_news_count():
    events = [
        _digest_event(keyword="A", title="a digest", priority="low", event_id="da"),
        _digest_event(keyword="B", title="b digest", priority="critical", event_id="db"),
        _digest_event(keyword="C", title="c digest", priority="medium", event_id="dc"),
    ]
    topics = _collect_tech_topics(events)
    keywords_in_order = [t.keyword for t in topics]
    assert keywords_in_order == ["B", "C", "A"]


def test_collect_tech_topics_caps_news_per_keyword():
    base = datetime(2026, 4, 13, tzinfo=timezone.utc)
    events = [
        _digest_event(keyword="X", title="X digest"),
    ]
    for i in range(8):
        events.append(_news_event(
            keyword="X",
            title=f"news {i}",
            occurred_at=base.replace(hour=i),
            event_id=f"n{i}",
        ))
    topics = _collect_tech_topics(events)
    assert len(topics[0].news_articles) == 5  # 키워드당 최대 5건


def test_collect_tech_topics_ignores_non_tech_events():
    events = [
        FakeEvent(
            id="lg1",
            source_type=SOURCE_LOGANALYZER,
            title="Some error",
            occurred_at=datetime(2026, 4, 13, tzinfo=timezone.utc),
            canonical={"keyword": "Java"},  # 일부러 keyword 가 있어도 무시되어야 함
        ),
        _news_event(keyword="Java", title="real java news"),
    ]
    topics = _collect_tech_topics(events)
    assert len(topics) == 1
    # loganalyzer 이벤트는 카운트되지 않아야 함
    assert len(topics[0].news_articles) == 1


def test_collect_tech_topics_skips_empty_keyword():
    events = [
        _news_event(keyword="", title="no keyword"),
        _news_event(keyword="   ", title="whitespace only"),
        _news_event(keyword="React", title="real"),
    ]
    topics = _collect_tech_topics(events)
    assert len(topics) == 1
    assert topics[0].keyword == "React"


# ── _build_tech_topic_items ──────────────────────────────────────────────
def test_build_tech_topic_items_strips_file_url_for_safety():
    topic = TechTopic(
        keyword="Java",
        digest_title="t",
        digest_url="file:///tmp/x.md",
    )
    [item] = _build_tech_topic_items([topic])
    # file:// 은 외부 발송 메일에서 클릭해도 의미 없으므로 link 로 노출 X
    assert item["digest_url"] == ""


def test_build_tech_topic_items_keeps_https_url():
    topic = TechTopic(
        keyword="Java",
        digest_title="t",
        digest_url="https://github.com/foo/bar/blob/main/x.md",
    )
    [item] = _build_tech_topic_items([topic])
    assert item["digest_url"].startswith("https://")


def test_build_tech_topic_items_lowercases_priority_for_badge_class():
    topic = TechTopic(keyword="X", digest_priority="HIGH")
    [item] = _build_tech_topic_items([topic])
    assert item["digest_priority"] == "high"


# ── 템플릿 렌더링 통합 ────────────────────────────────────────────────
def _make_synthesis(tech_topics: list[TechTopic]) -> SynthesisOutput:
    return SynthesisOutput(
        period_start=date(2026, 4, 7),
        period_end=date(2026, 4, 13),
        headline="테스트 헤드라인",
        markdown="# 테스트 헤드라인\n\n## 본문\n간단한 본문",
        kpis={"total_events": 1, "by_severity": {}, "by_service": {}, "by_source": {}},
        analysis={"recurring": [], "new": [], "improvements": [], "actions": []},
        summaries=[],
        source_event_ids=[],
        rag_refs=[],
        tech_topics=tech_topics,
    )


def test_render_newsletter_includes_tech_topic_section():
    syn = _make_synthesis([TechTopic(
        keyword="Java 21",
        digest_title="[Java 21] 적용 제안",
        digest_priority="high",
        digest_category="language-features",
        digest_difficulty="medium",
        digest_maturity="mainstream",
        digest_summary="Java 21 의 패턴 매칭 기능 도입",
        digest_target_scope="새 모듈",
        digest_risks="호환성 이슈 가능",
        digest_url="https://example.com/digest.md",
        news_articles=[
            {"title": "Java 21 release", "url": "https://news.example.com/r",
             "source": "google", "description": "...", "published_at": ""},
        ],
    )])
    result = render_newsletter(syn, include_tech_topics=True)
    html = result["html"]
    assert "이번 주 기술 토픽" in html
    assert "Java 21" in html
    assert "[Java 21] 적용 제안" in html
    assert "badge-high" in html
    assert "패턴 매칭" in html
    assert "https://news.example.com/r" in html
    assert "[google]" in html


def test_render_newsletter_omits_section_when_no_topics():
    syn = _make_synthesis([])
    result = render_newsletter(syn, include_tech_topics=True)
    assert "이번 주 기술 토픽" not in result["html"]


def test_render_newsletter_hides_tech_section_by_default():
    """TechBriefing 이관 — 기본값(설정 미변경)에서는 토픽이 있어도 섹션 미렌더."""
    syn = _make_synthesis([TechTopic(keyword="Java 21", digest_title="t")])
    result = render_newsletter(syn)
    assert "이번 주 기술 토픽" not in result["html"]


def test_render_newsletter_does_not_emit_anchor_for_file_url():
    syn = _make_synthesis([TechTopic(
        keyword="Java",
        digest_title="title",
        digest_url="file:///tmp/x.md",
    )])
    result = render_newsletter(syn, include_tech_topics=True)
    assert "file:///tmp/x.md" not in result["html"]


# ── PR-SU-11: medium-digest v2 필드 (_collect_tech_topics 안 전파) ────────

def test_collect_tech_topics_passes_v2_fields_into_topic():
    """canonical 에 importance_score / interpretation_* 가 있으면 TechTopic 에 흘러야."""
    ev = FakeEvent(
        id="dv2",
        source_type=SOURCE_MEDIUM_DIGEST_REPORT,
        title="[Spring Boot REST Clients] 적용 제안",
        occurred_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        canonical={
            "keyword": "Spring Boot REST Clients",
            "priority": "high",
            "category": "api-design",
            "difficulty": "low",
            "maturity": "mainstream",
            "tech_description": "Spring Boot 4 의 RestClient ...",
            "target_scope": "Controllers, services",
            "risks": "RestTemplate 마이그레이션",
            # PR-MDA-2/3 새 필드
            "importance_score": 78,
            "importance_factors": ["mainstream 채택", "api 직접 매핑"],
            "interpretation_core": "RestClient 도입으로 호출 단순화.",
            "interpretation_why": "Spring 6+ stable 이후 확산.",
            "interpretation_takeaways": [
                "RestTemplate → RestClient 마이그레이션",
                "fluent 가독성 향상",
                "WebClient 와 선택 기준 이해",
            ],
        },
    )
    topics = _collect_tech_topics([ev])
    assert len(topics) == 1
    t = topics[0]
    assert t.importance_score == 78
    assert t.importance_factors == ["mainstream 채택", "api 직접 매핑"]
    assert "RestClient" in t.interpretation_core
    assert "Spring 6" in t.interpretation_why
    assert len(t.interpretation_takeaways) == 3
    assert "마이그레이션" in t.interpretation_takeaways[0]


def test_collect_tech_topics_handles_missing_v2_fields_safely():
    """v2 필드 없는 옛 canonical 도 깨지지 않고 빈 default 로."""
    ev = _digest_event(keyword="Legacy", title="[Legacy] 적용", event_id="dv1")
    topics = _collect_tech_topics([ev])
    assert topics[0].importance_score is None
    assert topics[0].importance_factors == []
    assert topics[0].interpretation_core == ""
    assert topics[0].interpretation_takeaways == []
