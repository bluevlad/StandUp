"""tech_brief_detailer 단위 테스트 (PR5)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.article_image_extractor import ArticleMeta
from app.services.tech_topic_filter import FitnessResult
from app.synthesis.ollama_client import GenResult
from app.synthesis.pipeline import TechTopic
from app.synthesis.tech_brief_detailer import (
    CaseStudy,
    CodeHint,
    TopicDetail,
    _extract_mermaid,
    _parse_code_hints_json,
    _valid_file_set,
    collect_case_studies,
    detail_topic,
    generate_code_hints,
    generate_diagram,
)


def _gen_ok(text: str) -> GenResult:
    return GenResult(text=text, model="m", eval_count=1, eval_duration_ms=20, ok=True)


def _gen_fail() -> GenResult:
    return GenResult(text="", model="m", eval_count=0, eval_duration_ms=0,
                     ok=False, error="x")


# ── _extract_mermaid ─────────────────────────────────────────────────────

def test_extract_mermaid_from_fenced_block():
    raw = (
        "여기 다이어그램이 있습니다:\n"
        "```mermaid\nflowchart LR\n  A --> B\n```\n끝."
    )
    out = _extract_mermaid(raw)
    assert "flowchart LR" in out
    assert "A --> B" in out
    assert "```" not in out


def test_extract_mermaid_fallback_without_fence():
    raw = "flowchart TD\n  X --> Y"
    out = _extract_mermaid(raw)
    assert out.startswith("flowchart TD")


def test_extract_mermaid_returns_empty_when_none():
    assert _extract_mermaid("") == ""
    assert _extract_mermaid("아무 텍스트") == ""


# ── _parse_code_hints_json ────────────────────────────────────────────────

def test_parse_code_hints_array():
    raw = '[{"file":"api/x.java","change_sketch":"a","snippet":"s"}]'
    out = _parse_code_hints_json(raw)
    assert out == [{"file": "api/x.java", "change_sketch": "a", "snippet": "s"}]


def test_parse_code_hints_handles_code_fence():
    raw = "```json\n[{\"file\":\"x\",\"change_sketch\":\"y\"}]\n```"
    out = _parse_code_hints_json(raw)
    assert len(out) == 1
    assert out[0]["file"] == "x"


def test_parse_code_hints_empty_on_garbage():
    assert _parse_code_hints_json("not json") == []
    assert _parse_code_hints_json("") == []


# ── generate_diagram ─────────────────────────────────────────────────────

def test_generate_diagram_returns_mermaid_block():
    with patch(
        "app.synthesis.tech_brief_detailer.chat",
        return_value=_gen_ok("```mermaid\nflowchart LR\n  A --> B\n```"),
    ):
        mermaid, model, ms = generate_diagram(
            TechTopic(keyword="Spring", digest_summary="x"),
            repo_index={"summary": {"controllers": 1}},
        )
    assert "flowchart LR" in mermaid
    assert model  # 모델명 채워짐
    assert ms == 20


def test_generate_diagram_returns_empty_on_llm_failure():
    with patch(
        "app.synthesis.tech_brief_detailer.chat",
        return_value=_gen_fail(),
    ):
        mermaid, _, _ = generate_diagram(
            TechTopic(keyword="X"), repo_index={"summary": {}},
        )
    assert mermaid == ""


# ── collect_case_studies ─────────────────────────────────────────────────

def test_collect_case_studies_uses_og_image():
    topic = TechTopic(
        keyword="React",
        news_articles=[
            {"title": "T1", "url": "https://a.com/1", "source": "google",
             "description": "d1", "published_at": "2026-05-01T00:00:00"},
        ],
    )
    fake_meta = ArticleMeta(
        url="https://a.com/1",
        canonical_url="https://a.com/1",
        image_url="https://a.com/cover.png",
        title="실제 제목",
        description="실제 요약",
        site_name="DevBlog",
        fetched=True,
    )
    with patch(
        "app.synthesis.tech_brief_detailer.extract_many",
        return_value=[fake_meta],
    ):
        cases = collect_case_studies(topic)
    assert len(cases) == 1
    c = cases[0]
    assert isinstance(c, CaseStudy)
    assert c.image_url == "https://a.com/cover.png"
    assert c.title == "실제 제목"
    assert c.site_name == "DevBlog"
    assert c.source == "google"


def test_collect_case_studies_handles_fetch_failure():
    """fetch 실패해도 article 의 기본 정보로 카드 생성."""
    topic = TechTopic(
        keyword="React",
        news_articles=[
            {"title": "T1", "url": "https://a.com/1", "source": "google",
             "description": "fallback desc", "published_at": ""},
        ],
    )
    failed_meta = ArticleMeta(url="https://a.com/1", error="timeout", fetched=False)
    with patch(
        "app.synthesis.tech_brief_detailer.extract_many",
        return_value=[failed_meta],
    ):
        cases = collect_case_studies(topic)
    assert len(cases) == 1
    assert cases[0].image_url == ""
    assert cases[0].title == "T1"
    assert "fallback" in cases[0].description


def test_collect_case_studies_skips_non_http_urls():
    topic = TechTopic(
        keyword="Java",
        news_articles=[
            {"title": "bad", "url": "file:///local/x.md", "source": "google",
             "description": "", "published_at": ""},
        ],
    )
    with patch(
        "app.synthesis.tech_brief_detailer.extract_many", return_value=[],
    ):
        cases = collect_case_studies(topic)
    assert cases == []


# ── generate_code_hints ──────────────────────────────────────────────────

REPO_IDX = {
    "controllers": [{"class": "AuthController", "file": "api/AuthController.java"}],
    "entities":    [{"class": "User",           "file": "api/User.java"}],
    "services":    [],
    "web_admin_pages": [{"name": "Dashboard", "file": "web-admin/src/pages/Dashboard.tsx"}],
    "web_user_pages": [], "web_shared_pages": [],
    "summary": {"controllers": 1, "entities": 1, "services": 0,
                "web_admin_pages": 1, "web_user_pages": 0, "web_shared_pages": 0},
}


def test_valid_file_set_collects_all_paths():
    files = _valid_file_set(REPO_IDX)
    assert "api/AuthController.java" in files
    assert "web-admin/src/pages/Dashboard.tsx" in files


def test_generate_code_hints_filters_to_valid_files():
    response = (
        '[{"file":"api/AuthController.java","change_sketch":"X","snippet":""},'
        '{"file":"api/Imaginary.java","change_sketch":"fake","snippet":""}]'
    )
    with patch(
        "app.synthesis.tech_brief_detailer.chat",
        return_value=_gen_ok(response),
    ):
        hints, _, _ = generate_code_hints(
            TechTopic(keyword="Spring"), REPO_IDX,
            fitness=FitnessResult(
                score=75, eligible=True, matched_stack_tags=[],
                impact_area="backend-api", effort_hours=4, reason="r",
                stack_score=40, llm_score=35, model="m", eval_ms=0,
            ),
        )
    assert len(hints) == 2
    valid_hint = next(h for h in hints if h.file == "api/AuthController.java")
    fake_hint = next(h for h in hints if h.file == "api/Imaginary.java")
    assert "⚠" not in valid_hint.change_sketch
    assert "⚠" in fake_hint.change_sketch


def test_generate_code_hints_empty_on_llm_failure():
    with patch(
        "app.synthesis.tech_brief_detailer.chat", return_value=_gen_fail(),
    ):
        hints, _, _ = generate_code_hints(TechTopic(keyword="X"), REPO_IDX)
    assert hints == []


# ── detail_topic 통합 ────────────────────────────────────────────────────

def test_detail_topic_aggregates_three_signals():
    topic = TechTopic(
        keyword="Spring Boot",
        news_articles=[
            {"title": "A", "url": "https://a.com/1", "source": "google",
             "description": "d", "published_at": ""},
        ],
    )
    diagram_resp = "```mermaid\nflowchart LR\n  A --> B\n```"
    hints_resp = '[{"file":"api/AuthController.java","change_sketch":"s","snippet":""}]'
    chat_responses = iter([_gen_ok(diagram_resp), _gen_ok(hints_resp)])

    fake_meta = ArticleMeta(
        url="https://a.com/1", image_url="https://a.com/x.png",
        title="title", description="desc", fetched=True,
    )

    with patch(
        "app.synthesis.tech_brief_detailer.chat",
        side_effect=lambda **kw: next(chat_responses),
    ), patch(
        "app.synthesis.tech_brief_detailer.extract_many",
        return_value=[fake_meta],
    ):
        detail = detail_topic(topic, repo_index=REPO_IDX)

    assert isinstance(detail, TopicDetail)
    assert "flowchart LR" in detail.diagram_mermaid
    assert len(detail.case_studies) == 1
    assert detail.case_studies[0].image_url == "https://a.com/x.png"
    assert len(detail.code_hints) == 1
    assert detail.code_hints[0].file == "api/AuthController.java"
    assert detail.errors == []


def test_detail_topic_partial_failure_other_stages_ok():
    topic = TechTopic(keyword="Java")
    # 1 호출(diagram) 실패, 2 호출(code hints) 성공
    hints_resp = '[{"file":"api/User.java","change_sketch":"s","snippet":""}]'
    chat_responses = iter([_gen_fail(), _gen_ok(hints_resp)])

    with patch(
        "app.synthesis.tech_brief_detailer.chat",
        side_effect=lambda **kw: next(chat_responses),
    ), patch(
        "app.synthesis.tech_brief_detailer.extract_many",
        return_value=[],
    ):
        detail = detail_topic(topic, repo_index=REPO_IDX)

    assert detail.diagram_mermaid == ""
    assert detail.case_studies == []
    assert len(detail.code_hints) == 1


def test_detail_topic_skip_flags_skip_all_when_set():
    topic = TechTopic(keyword="Java")
    with patch("app.synthesis.tech_brief_detailer.chat") as chat_mock, patch(
        "app.synthesis.tech_brief_detailer.extract_many",
    ) as fetch_mock:
        detail = detail_topic(
            topic, repo_index=REPO_IDX,
            skip_diagram=True, skip_cases=True, skip_code_hints=True,
        )
        assert not chat_mock.called
        assert not fetch_mock.called

    assert detail.diagram_mermaid == ""
    assert detail.case_studies == []
    assert detail.code_hints == []
    assert detail.errors == []


def test_topic_detail_to_storage_dict_structure():
    detail = TopicDetail(
        diagram_mermaid="flowchart LR\nA-->B",
        case_studies=[CaseStudy(title="t", url="u", image_url="i")],
        code_hints=[CodeHint(file="f", change_sketch="s", snippet="x")],
    )
    storage = detail.to_storage_dict()
    assert storage["diagram_mermaid"] == "flowchart LR\nA-->B"
    assert storage["case_studies"][0]["title"] == "t"
    assert storage["case_studies"][0]["image_url"] == "i"
    assert storage["code_hints"][0]["file"] == "f"
