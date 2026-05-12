"""HopenVision Tech Brief Detailer (PR5).

게이트(`tech_topic_filter.evaluate_topic`) 를 통과한 토픽에 대해 *상세 산출물* 을
생성한다. 세 가지 신호를 한 번에 묶어 반환:

1. **Mermaid 다이어그램** — As-Is / To-Be 흐름. `qwen2.5-coder` 로 생성.
   파서 가능한 ```mermaid``` 블록을 추출, 실패 시 None.
2. **적용 사례 (case_studies)** — TechTopic.news_articles 각 URL 에서 og:image/canonical
   메타만 추출(`article_image_extractor`). 이메일에 카드로 표현 가능한 dict 리스트.
3. **PoC 코드 힌트 (code_hints)** — repo index 의 실파일 경로를 LLM 에 노출해
   `[{"file": "...", "change_sketch": "..."}, ...]` 로 응답받음.

세 단계는 독립적으로 실패해도 다른 단계가 계속 진행되며, 부분 산출도 의미가 있다.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from ..core.config import settings
from ..services.article_image_extractor import (
    ArticleMeta, extract_many,
)
from ..services.hopenvision_repo_indexer import condense_for_prompt
from .ollama_client import chat

if TYPE_CHECKING:
    from ..services.tech_topic_filter import FitnessResult
    from .pipeline import TechTopic

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)
_ARRAY_BLOCK_RE = re.compile(r"\[.*\]", re.DOTALL)
_MERMAID_BLOCK_RE = re.compile(
    r"```mermaid\s*\n(.+?)```", re.DOTALL | re.IGNORECASE,
)
_MERMAID_HEAD_RE = re.compile(
    r"^\s*(flowchart|graph|sequenceDiagram|classDiagram|stateDiagram|erDiagram)\b",
    re.IGNORECASE | re.MULTILINE,
)

_DIAGRAM_SYSTEM = """당신은 HopenVision (Spring Boot + React) 의 시니어 엔지니어다.
외부 기술 토픽이 어떻게 HopenVision 에 적용될지를 Mermaid 다이어그램 1개로 표현한다.

규칙:
- 응답은 반드시 ```mermaid 코드블록 1개만``` (앞뒤 설명 금지)
- flowchart LR 또는 sequenceDiagram 형식
- As-Is / To-Be 흐름을 2단으로 분리해 비교 (subgraph "현재" / subgraph "도입 후")
- 노드명은 repo index 에 실제로 있는 모듈/엔티티/페이지만 사용
- 한국어 라벨 가능"""

_CODE_HINTS_SYSTEM = """당신은 HopenVision 의 시니어 엔지니어다. 외부 토픽 적용을 위해
*실제 변경이 필요한 파일과 변경 스케치* 를 제안한다.

응답은 반드시 순수 JSON 배열:
[
  {"file": "repo index 에 명시된 실파일 경로", "change_sketch": "1-2 문장 한국어 변경 요지",
   "snippet": "5~12줄 의사코드 또는 diff 형식 (옵션, 없으면 빈 문자열)"}
]

규칙:
- 2~4 개 항목
- file 은 repo index 에 실제로 있는 경로만 사용 (없는 파일 만들지 말 것)
- 추측이 과하지 않게, 토픽 키워드와 직접 연결되는 항목만"""


@dataclass
class CaseStudy:
    """뉴스 article 1건 → 카드형 표현 가능한 dict."""

    title: str
    url: str
    image_url: str = ""
    description: str = ""
    site_name: str = ""
    source: str = ""  # google | naver
    published_at: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "image_url": self.image_url,
            "description": self.description,
            "site_name": self.site_name,
            "source": self.source,
            "published_at": self.published_at,
        }


@dataclass
class CodeHint:
    file: str
    change_sketch: str
    snippet: str = ""

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "change_sketch": self.change_sketch,
            "snippet": self.snippet,
        }


@dataclass
class TopicDetail:
    """detailer 의 전체 산출물 — proposal 행에 그대로 저장 가능한 형태."""

    diagram_mermaid: str = ""           # Mermaid 코드 (없으면 빈 문자열)
    case_studies: list[CaseStudy] = field(default_factory=list)
    code_hints: list[CodeHint] = field(default_factory=list)
    diagram_model: str = ""
    code_hints_model: str = ""
    diagram_eval_ms: int = 0
    code_hints_eval_ms: int = 0
    errors: list[str] = field(default_factory=list)

    def to_storage_dict(self) -> dict:
        return {
            "diagram_mermaid": self.diagram_mermaid,
            "case_studies": [c.to_dict() for c in self.case_studies],
            "code_hints": [h.to_dict() for h in self.code_hints],
        }


# ── 1. Mermaid 다이어그램 ────────────────────────────────────────────────

def _extract_mermaid(raw: str) -> str:
    """LLM 응답에서 mermaid 블록만 추출. 코드펜스 없으면 헤더 키워드로 fallback."""
    if not raw:
        return ""
    m = _MERMAID_BLOCK_RE.search(raw)
    if m:
        return m.group(1).strip()
    # 코드펜스 없이 바로 flowchart/sequenceDiagram 로 시작하는 경우
    h = _MERMAID_HEAD_RE.search(raw)
    if h:
        return raw[h.start():].strip().strip("`").strip()
    return ""


def _build_diagram_prompt(topic: "TechTopic", repo_summary: str) -> str:
    parts = ["[외부 기술 토픽]", f"키워드: {topic.keyword}"]
    if topic.digest_title:
        parts.append(f"디지스트 제목: {topic.digest_title}")
    if topic.digest_summary:
        parts.append(f"설명: {topic.digest_summary[:400]}")
    if topic.digest_target_scope:
        parts.append(f"적용 대상(외부): {topic.digest_target_scope[:300]}")
    parts.append("")
    parts.append(repo_summary)
    parts.append("")
    parts.append(
        "위 토픽을 HopenVision 에 도입하기 전/후 흐름을 Mermaid 다이어그램 1개로 표현하라. "
        "현재(As-Is) 와 도입 후(To-Be) 를 subgraph 로 나누어 비교할 것."
    )
    return "\n".join(parts)


def generate_diagram(
    topic: "TechTopic",
    repo_index: Optional[dict] = None,
) -> tuple[str, str, int]:
    """Mermaid 다이어그램 텍스트 생성. (mermaid, model, eval_ms)."""
    repo_summary = condense_for_prompt(repo_index or {})
    prompt = _build_diagram_prompt(topic, repo_summary)
    gen = chat(
        model=settings.ollama_model_analyze,
        system=_DIAGRAM_SYSTEM,
        user=prompt,
        temperature=0.2,
        max_tokens=800,
    )
    if not gen.ok:
        return "", settings.ollama_model_analyze, gen.eval_duration_ms
    return _extract_mermaid(gen.text), settings.ollama_model_analyze, gen.eval_duration_ms


# ── 2. 적용 사례 (og:image) ──────────────────────────────────────────────

def collect_case_studies(
    topic: "TechTopic",
    *,
    max_cases: int = 3,
    timeout: int = 6,
) -> list[CaseStudy]:
    """news_articles URL 들에서 og:image 메타 추출 → CaseStudy 리스트.

    Args:
        topic: TechTopic — `news_articles` 가 사례 후보.
        max_cases: 외부 fetch 가 비싸므로 상한.
        timeout: 1건당 fetch 타임아웃.
    """
    if not topic.news_articles:
        return []

    candidates = [a for a in topic.news_articles if a.get("url", "").startswith(("http://", "https://"))]
    if not candidates:
        return []

    urls = [a["url"] for a in candidates[:max_cases]]
    metas = extract_many(urls, timeout=timeout, limit=max_cases)

    out: list[CaseStudy] = []
    for art, meta in zip(candidates, metas):
        # fetched=False 여도 article 의 기본 정보로 카드 생성 (image_url 만 빈 상태)
        out.append(CaseStudy(
            title=meta.title or art.get("title", ""),
            url=(meta.canonical_url or art.get("url", "")),
            image_url=meta.image_url or "",
            description=(meta.description or art.get("description", ""))[:240],
            site_name=meta.site_name or "",
            source=art.get("source", ""),
            published_at=art.get("published_at", ""),
        ))
    return out


# ── 3. PoC 코드 힌트 ─────────────────────────────────────────────────────

def _parse_code_hints_json(raw: str) -> list[dict]:
    if not raw:
        return []
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    m = _ARRAY_BLOCK_RE.search(cleaned)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
    except json.JSONDecodeError as e:
        logger.warning("code_hints JSON 파싱 실패: %s", e)
    return []


def _build_code_hints_prompt(
    topic: "TechTopic",
    repo_summary: str,
    fitness: Optional["FitnessResult"] = None,
) -> str:
    parts = ["[외부 기술 토픽]", f"키워드: {topic.keyword}"]
    if topic.digest_summary:
        parts.append(f"설명: {topic.digest_summary[:400]}")
    if topic.digest_target_scope:
        parts.append(f"적용 대상(외부): {topic.digest_target_scope[:300]}")
    parts.append("")
    parts.append(repo_summary)
    if fitness is not None:
        parts.append("")
        parts.append(
            f"[적합도 평가] score={fitness.score}/100, impact_area={fitness.impact_area}"
        )
        if fitness.reason:
            parts.append(f"  reason: {fitness.reason}")
    parts.append("")
    parts.append(
        "위 토픽을 도입하기 위해 실제로 변경이 필요한 파일과 변경 스케치를 "
        "JSON 배열로 응답하라. repo index 에 실재하는 파일만 file 로 사용."
    )
    return "\n".join(parts)


def generate_code_hints(
    topic: "TechTopic",
    repo_index: Optional[dict] = None,
    fitness: Optional["FitnessResult"] = None,
    *,
    max_hints: int = 4,
) -> tuple[list[CodeHint], str, int]:
    """LLM 으로 PoC 코드 힌트 생성. (hints, model, eval_ms)."""
    repo_summary = condense_for_prompt(repo_index or {})
    prompt = _build_code_hints_prompt(topic, repo_summary, fitness)
    gen = chat(
        model=settings.ollama_model_analyze,
        system=_CODE_HINTS_SYSTEM,
        user=prompt,
        temperature=0.2,
        max_tokens=900,
    )
    if not gen.ok:
        return [], settings.ollama_model_analyze, gen.eval_duration_ms

    items = _parse_code_hints_json(gen.text)
    valid_files = _valid_file_set(repo_index or {})
    hints: list[CodeHint] = []
    for d in items[:max_hints]:
        file_ = (d.get("file") or "").strip()
        sketch = (d.get("change_sketch") or "").strip()
        snippet = (d.get("snippet") or "")
        if not file_ or not sketch:
            continue
        # repo index 에 없는 파일이면 hallucination 가능성 → 표시는 하되 별도 마크
        if valid_files and file_ not in valid_files:
            sketch = f"[⚠ repo index 외 경로] {sketch}"
        hints.append(CodeHint(
            file=file_,
            change_sketch=sketch[:400],
            snippet=str(snippet)[:1200],
        ))
    return hints, settings.ollama_model_analyze, gen.eval_duration_ms


def _valid_file_set(repo_index: dict) -> set[str]:
    """repo_index 안에 등장한 파일 경로 전체 — hallucination 가드용."""
    out: set[str] = set()
    for section in ("controllers", "entities", "services",
                    "web_admin_pages", "web_user_pages", "web_shared_pages"):
        for item in repo_index.get(section, []):
            f = (item or {}).get("file") if isinstance(item, dict) else None
            if f:
                out.add(f)
    return out


# ── 통합 진입점 ──────────────────────────────────────────────────────────

def detail_topic(
    topic: "TechTopic",
    repo_index: Optional[dict] = None,
    fitness: Optional["FitnessResult"] = None,
    *,
    skip_diagram: bool = False,
    skip_cases: bool = False,
    skip_code_hints: bool = False,
) -> TopicDetail:
    """게이트 통과 토픽 → 상세 산출물 통합 생성. 단계별 실패는 흡수."""
    detail = TopicDetail()

    # 1) Mermaid 다이어그램
    if not skip_diagram:
        try:
            mermaid, model, ms = generate_diagram(topic, repo_index)
            detail.diagram_mermaid = mermaid
            detail.diagram_model = model
            detail.diagram_eval_ms = ms
        except Exception as e:  # noqa: BLE001
            logger.warning("diagram 생성 실패 keyword=%s: %s", topic.keyword, e)
            detail.errors.append(f"diagram: {e}")

    # 2) 적용 사례 (외부 fetch — 실패해도 다른 단계 진행)
    if not skip_cases:
        try:
            detail.case_studies = collect_case_studies(topic)
        except Exception as e:  # noqa: BLE001
            logger.warning("case_studies 수집 실패 keyword=%s: %s", topic.keyword, e)
            detail.errors.append(f"cases: {e}")

    # 3) PoC 코드 힌트
    if not skip_code_hints:
        try:
            hints, model, ms = generate_code_hints(topic, repo_index, fitness)
            detail.code_hints = hints
            detail.code_hints_model = model
            detail.code_hints_eval_ms = ms
        except Exception as e:  # noqa: BLE001
            logger.warning("code_hints 생성 실패 keyword=%s: %s", topic.keyword, e)
            detail.errors.append(f"code_hints: {e}")

    return detail
