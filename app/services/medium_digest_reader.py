"""medium-digest-agent 가 생성한 Markdown 리포트 리더.

리포트 디렉토리(예: /Users/rainend/GIT/medium-digest-agent/reports/) 에서
파일명이 `YYYY-MM-DD-{slug}.md` 인 리포트를 파싱해 구조화 dict 로 반환한다.
StandUp 자체적으로 메일을 다시 가져오지 않고 medium-digest-agent 의 산출물만
흡수해 뉴스레터 합성/HopenVision 제안 입력으로 활용한다.

리포트 헤더 섹션 예 (한글 고정):

    # [Java 21+] 적용 제안 — academy-admin/backend

    ## 요약
    - **기술 키워드**: Java 21+
    - **카테고리**: language-features
    - **출처 뉴스레터**: ...
    - **분석일**: 2026-04-13
    - **우선순위**: medium
    - **도입 난이도**: medium
    - **기술 성숙도**: mainstream

    ## 참고 자료
    - [Title - Source](https://...)
    - [Title - Source](https://...)

    ## 기술 설명
    Java 21은 ...

    ## 현재 서비스 현황
    ...

    ## 적용 대상
    | 모듈 영역 | ... |

    ## 변경 사항
    ...

    ## 예상 효과
    ...

    ## 리스크 및 롤백 전략
    ...

이 모듈은 medium-digest-agent 의 출력 포맷이 위 구조를 유지한다는 가정을 따른다.
포맷이 바뀌면 `_SECTION_ALIASES` 만 보강하면 된다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)\.md$")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BULLET_KV_RE = re.compile(r"^[-*]\s*\*\*(?P<key>[^:*]+)\*\*\s*[:：]\s*(?P<value>.+)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s*(.+?)\s*$")

# 섹션 별칭 — 한글 표기 흔들림 흡수용
_SECTION_ALIASES = {
    "요약": "summary",
    "참고 자료": "references",
    "참고자료": "references",
    "기술 설명": "tech_description",
    "기술설명": "tech_description",
    "현재 서비스 현황": "current_state",
    "적용 대상": "target_scope",
    "변경 사항": "changes",
    "예상 효과": "expected_effects",
    "리스크 및 롤백 전략": "risks",
    "리스크": "risks",
    "파일럿 적용 범위": "pilot_scope",
    "승인": "approval",
}

# 메타데이터 키 별칭
_META_KEY_ALIASES = {
    "기술 키워드": "keyword",
    "카테고리": "category",
    "출처 뉴스레터": "source_newsletter",
    "분석일": "analyzed_date",
    "우선순위": "priority",
    "도입 난이도": "difficulty",
    "기술 성숙도": "maturity",
}


@dataclass
class DigestReport:
    """파싱된 medium-digest-agent 리포트."""

    file_path: Path
    file_date: date
    slug: str
    title: str                                  # H1
    keyword: str = ""                           # 요약 메타: 기술 키워드
    category: str = ""
    source_newsletter: str = ""
    priority: str = ""
    difficulty: str = ""
    maturity: str = ""
    references: list[dict[str, str]] = field(default_factory=list)  # [{title,url}]
    tech_description: str = ""
    current_state: str = ""
    target_scope: str = ""
    changes: str = ""
    expected_effects: str = ""
    risks: str = ""
    pilot_scope: str = ""
    raw_text: str = ""

    @property
    def occurred_at(self) -> datetime:
        """뉴스레터 timeline 용 KST 자정 timestamp."""
        return datetime.combine(self.file_date, time(0, 0), tzinfo=timezone.utc)

    @property
    def source_id(self) -> str:
        return f"{self.file_date.isoformat()}-{self.slug}"

    @property
    def short_excerpt(self) -> str:
        body = self.tech_description or self.current_state or self.expected_effects
        body = body.replace("\n", " ").strip()
        return (body[:240] + "…") if len(body) > 240 else body


def _parse_summary_bullets(lines: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in lines:
        m = _BULLET_KV_RE.match(line.strip())
        if not m:
            continue
        key = m.group("key").strip()
        value = m.group("value").strip()
        canonical = _META_KEY_ALIASES.get(key)
        if canonical:
            out[canonical] = value
    return out


def _parse_reference_links(lines: list[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for line in lines:
        for title, url in _LINK_RE.findall(line):
            out.append({"title": title.strip(), "url": url.strip()})
    return out


def _split_sections(text: str) -> tuple[str, dict[str, list[str]]]:
    """H1 제목 + (H2 섹션명 → 라인 리스트) 매핑으로 분해."""
    title = ""
    sections: dict[str, list[str]] = {}
    current: Optional[str] = None
    buffer: list[str] = []

    def flush():
        nonlocal buffer
        if current is not None:
            sections.setdefault(current, []).extend(buffer)
        buffer = []

    for raw_line in text.splitlines():
        m = _HEADING_RE.match(raw_line)
        if m:
            level = len(m.group(1))
            heading = m.group(2).strip()
            if level == 1 and not title:
                title = heading
                continue
            if level == 2:
                flush()
                canonical = _SECTION_ALIASES.get(heading.strip())
                current = canonical or heading.strip()
                continue
        if current is not None:
            buffer.append(raw_line)
    flush()
    return title, sections


def _join(lines: list[str]) -> str:
    # leading/trailing 공백 라인 제거 후 join
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_report(file_path: Path) -> Optional[DigestReport]:
    """단일 markdown 리포트 파싱. 실패 시 None."""
    name = file_path.name
    fname_match = _FILENAME_RE.match(name)
    if not fname_match:
        return None
    file_date = date.fromisoformat(fname_match.group(1))
    slug = fname_match.group(2)

    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("digest 리포트 읽기 실패 %s: %s", file_path, e)
        return None

    title, sections = _split_sections(text)
    summary_meta = _parse_summary_bullets(sections.get("summary", []))
    refs = _parse_reference_links(sections.get("references", []))

    return DigestReport(
        file_path=file_path,
        file_date=file_date,
        slug=slug,
        title=title or slug,
        keyword=summary_meta.get("keyword", ""),
        category=summary_meta.get("category", ""),
        source_newsletter=summary_meta.get("source_newsletter", ""),
        priority=summary_meta.get("priority", ""),
        difficulty=summary_meta.get("difficulty", ""),
        maturity=summary_meta.get("maturity", ""),
        references=refs,
        tech_description=_join(sections.get("tech_description", [])),
        current_state=_join(sections.get("current_state", [])),
        target_scope=_join(sections.get("target_scope", [])),
        changes=_join(sections.get("changes", [])),
        expected_effects=_join(sections.get("expected_effects", [])),
        risks=_join(sections.get("risks", [])),
        pilot_scope=_join(sections.get("pilot_scope", [])),
        raw_text=text,
    )


def _matches_keyword_filter(report: DigestReport, allow: set[str]) -> bool:
    """allow 가 비어있으면 모두 통과. 아니면 keyword/category/title 부분 매칭."""
    if not allow:
        return True
    haystack = " ".join([
        report.keyword, report.category, report.title, report.slug,
    ]).lower()
    return any(token in haystack for token in allow)


class MediumDigestReaderService:
    """리포트 디렉토리를 [since, until] 윈도우로 스캔."""

    def __init__(self, reports_dir: str, keywords: Optional[list[str]] = None):
        self.reports_dir = Path(reports_dir) if reports_dir else None
        self._keyword_filter = {k.strip().lower() for k in (keywords or []) if k.strip()}

    def is_available(self) -> bool:
        return self.reports_dir is not None and self.reports_dir.is_dir()

    def list_reports(
        self,
        since: datetime,
        until: datetime,
    ) -> list[DigestReport]:
        if not self.is_available():
            return []
        assert self.reports_dir is not None  # is_available 가 True 일 때만

        since_d = since.date()
        until_d = until.date()
        out: list[DigestReport] = []
        for path in sorted(self.reports_dir.glob("*.md")):
            m = _FILENAME_RE.match(path.name)
            if not m:
                continue
            try:
                file_date = date.fromisoformat(m.group(1))
            except ValueError:
                continue
            if file_date < since_d or file_date > until_d:
                continue
            report = parse_report(path)
            if report is None:
                continue
            if not _matches_keyword_filter(report, self._keyword_filter):
                continue
            out.append(report)
        return out
