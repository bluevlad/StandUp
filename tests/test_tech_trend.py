"""TechTrend connector 단위 테스트.

- medium-digest-agent 가 만드는 markdown 리포트 파싱 (실제 샘플 사용)
- TechNewsSearchService 의 키워드 병렬 검색 (네트워크 모킹)
- TechTrendConnector 가 두 채널을 합쳐 CanonicalEvent 로 정규화하는 로직
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app.ingestion.connectors.tech_trend import TechTrendConnector
from app.models.insight import (
    COLLECTION_TECH,
    SOURCE_MEDIUM_DIGEST_REPORT,
    SOURCE_TECH_NEWS_ARTICLE,
)
from app.services.medium_digest_reader import (
    MediumDigestReaderService,
    parse_report,
)
from app.services.tech_news_search import (
    KeywordSearchResult,
    NewsArticle,
    TechNewsSearchService,
)

FIXTURES = Path(__file__).parent / "fixtures" / "digest_reports"


# ── fixture 생성 ──────────────────────────────────────────────────────────
SAMPLE_MD = """\
# [Java 21+] 적용 제안 — academy-admin/backend

## 요약
- **기술 키워드**: Java 21+
- **카테고리**: language-features
- **출처 뉴스레터**: Java 25 Features That Will Change the Way You Code Forever
- **분석일**: 2026-04-13
- **우선순위**: medium
- **도입 난이도**: medium
- **기술 성숙도**: mainstream

## 참고 자료
- [Oracle Releases Java 26 - Oracle](https://news.google.com/foo)
- [How to enable Java 21 preview features - TheServerSide](https://news.google.com/bar)

## 기술 설명

Java 21은 패턴 매칭, sealed 클래스, 레코드 등의 기능을 도입했습니다.

## 현재 서비스 현황

- Spring Boot 3.2.0, Java 21
- MySQL

## 적용 대상

| 모듈 영역 | 대상 파일 유형 | 변경 내용 |
|---|---|---|
| 새로운 개발 모듈 | *Api.java | 패턴 매칭 활용 |

## 변경 사항

```java
switch (day) {
    case MONDAY -> System.out.println("Start");
}
```

## 예상 효과
- 가독성 향상

## 리스크 및 롤백 전략
- 호환성 이슈 가능성

## 파일럿 적용 범위
새 모듈에서 먼저 검증

## 승인
- [ ] 관리자 승인
"""


@pytest.fixture(scope="module")
def sample_report_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("digest_reports")
    (d / "2026-04-13-java-21.md").write_text(SAMPLE_MD, encoding="utf-8")
    # 다른 날짜 파일 — keyword filter 테스트용
    other = SAMPLE_MD.replace("Java 21+", "React 19").replace(
        "language-features", "frontend",
    ).replace("2026-04-13", "2026-04-14")
    (d / "2026-04-14-react-19.md").write_text(other, encoding="utf-8")
    # 윈도우 밖 (오래된 것)
    (d / "2025-01-01-old.md").write_text(SAMPLE_MD, encoding="utf-8")
    # 파일명 형식 안 맞는 것
    (d / "README.md").write_text("# not a digest", encoding="utf-8")
    return d


# ── parse_report ────────────────────────────────────────────────────────
def test_parse_report_extracts_metadata(sample_report_dir):
    report = parse_report(sample_report_dir / "2026-04-13-java-21.md")
    assert report is not None
    assert report.title.startswith("[Java 21+]")
    assert report.keyword == "Java 21+"
    assert report.category == "language-features"
    assert report.priority == "medium"
    assert report.difficulty == "medium"
    assert report.maturity == "mainstream"
    assert report.file_date.isoformat() == "2026-04-13"
    assert report.slug == "java-21"


def test_parse_report_extracts_references(sample_report_dir):
    report = parse_report(sample_report_dir / "2026-04-13-java-21.md")
    assert report is not None
    urls = [r["url"] for r in report.references]
    assert "https://news.google.com/foo" in urls
    assert "https://news.google.com/bar" in urls


def test_parse_report_extracts_sections(sample_report_dir):
    report = parse_report(sample_report_dir / "2026-04-13-java-21.md")
    assert report is not None
    assert "패턴 매칭" in report.tech_description
    assert "Spring Boot" in report.current_state
    assert "*Api.java" in report.target_scope
    assert "case MONDAY" in report.changes
    assert "가독성" in report.expected_effects
    assert "호환성" in report.risks
    assert "새 모듈" in report.pilot_scope


def test_parse_report_returns_none_for_invalid_filename(tmp_path):
    bad = tmp_path / "no-date.md"
    bad.write_text("# x", encoding="utf-8")
    assert parse_report(bad) is None


# ── MediumDigestReaderService ───────────────────────────────────────────
def test_reader_window_filters_by_date(sample_report_dir):
    svc = MediumDigestReaderService(reports_dir=str(sample_report_dir))
    since = datetime(2026, 4, 13, tzinfo=timezone.utc)
    until = datetime(2026, 4, 14, tzinfo=timezone.utc)
    reports = svc.list_reports(since, until)
    slugs = {r.slug for r in reports}
    assert slugs == {"java-21", "react-19"}


def test_reader_keyword_filter_matches_substring(sample_report_dir):
    svc = MediumDigestReaderService(
        reports_dir=str(sample_report_dir), keywords=["java"],
    )
    since = datetime(2026, 4, 13, tzinfo=timezone.utc)
    until = datetime(2026, 4, 14, tzinfo=timezone.utc)
    reports = svc.list_reports(since, until)
    assert {r.slug for r in reports} == {"java-21"}


def test_reader_unavailable_when_dir_missing():
    svc = MediumDigestReaderService(reports_dir="/nonexistent/path/zzz")
    assert not svc.is_available()
    assert svc.list_reports(
        datetime(2026, 4, 13, tzinfo=timezone.utc),
        datetime(2026, 4, 14, tzinfo=timezone.utc),
    ) == []


# ── TechNewsSearchService ────────────────────────────────────────────────
def test_news_service_dedupes_across_sources():
    svc = TechNewsSearchService(
        max_per_keyword=5, workers=2, timeout=5,
        naver_client_id="", naver_client_secret="",  # naver 비활성
    )
    duplicate_url = "https://news.example.com/post/1"
    duplicate_title = "Java 26 released"

    google_articles = [
        NewsArticle(
            title=duplicate_title, url=duplicate_url, source="google",
            description="d1", published_at=None, search_keyword="java",
        ),
        NewsArticle(
            title="Other Java news", url="https://news.example.com/post/2",
            source="google", description="d2", published_at=None,
            search_keyword="java",
        ),
    ]
    naver_articles = [
        NewsArticle(
            title=duplicate_title, url=duplicate_url, source="naver",
            description="d1-naver", published_at=None, search_keyword="java",
        ),
    ]

    with patch.object(svc.google, "search", return_value=google_articles), \
         patch.object(svc.naver, "search", return_value=naver_articles):
        result = svc.search_one("java")

    urls = [a.url for a in result.articles]
    assert urls.count(duplicate_url) == 1, "중복 URL 이 한 번만 포함되어야 함"
    assert "https://news.example.com/post/2" in urls


def test_news_service_search_many_returns_keyword_map():
    svc = TechNewsSearchService(
        max_per_keyword=5, workers=2, timeout=5,
        naver_client_id="", naver_client_secret="",
    )

    def fake_one(keyword: str) -> KeywordSearchResult:
        return KeywordSearchResult(
            keyword=keyword,
            articles=[NewsArticle(
                title=f"{keyword} title", url=f"https://x.com/{keyword}",
                source="google", description="d", published_at=None,
                search_keyword=keyword,
            )],
        )

    with patch.object(svc, "search_one", side_effect=fake_one):
        result = svc.search_many(["java", "react"])
    assert set(result.keys()) == {"java", "react"}
    assert result["java"].articles[0].title == "java title"


# ── TechTrendConnector 통합 ────────────────────────────────────────────
def test_connector_builds_canonical_events(sample_report_dir):
    # 가짜 NewsService — 외부 호출 없이 KeywordSearchResult 반환
    class FakeNewsService:
        def search_many(self, keywords):
            return {
                kw: KeywordSearchResult(
                    keyword=kw,
                    articles=[NewsArticle(
                        title=f"{kw} weekly news",
                        url=f"https://news.example.com/{kw}",
                        source="google",
                        description=f"about {kw}",
                        published_at=datetime(2026, 4, 13, 12, tzinfo=timezone.utc),
                        search_keyword=kw,
                    )],
                )
                for kw in keywords
            }

    digest_reader = MediumDigestReaderService(
        reports_dir=str(sample_report_dir),
        keywords=["java", "react"],
    )
    connector = TechTrendConnector(
        keywords=["java", "react"],
        reports_dir=str(sample_report_dir),
        digest_reader=digest_reader,
        news_service=FakeNewsService(),
    )

    since = datetime(2026, 4, 12, tzinfo=timezone.utc)
    until = datetime(2026, 4, 14, 23, 59, tzinfo=timezone.utc)
    res = connector.fetch(since, until)

    assert res.error is None
    sources = [e.source_type for e in res.events]
    # digest 2건(java/react) + 뉴스 2건(java/react) = 4건
    assert sources.count(SOURCE_MEDIUM_DIGEST_REPORT) == 2
    assert sources.count(SOURCE_TECH_NEWS_ARTICLE) == 2

    # corpus_tech 컬렉션으로만 chunk 가 만들어지는지
    for ev in res.events:
        assert ev.extra_chunks, f"{ev.source_type} 청크 누락"
        for ch in ev.extra_chunks:
            assert ch.collection == COLLECTION_TECH


def test_connector_handles_empty_reports_dir():
    connector = TechTrendConnector(
        keywords=[],
        reports_dir="",
        digest_reader=MediumDigestReaderService(reports_dir=""),
        news_service=TechNewsSearchService(
            max_per_keyword=1, workers=1, timeout=1,
            naver_client_id="", naver_client_secret="",
        ),
    )
    res = connector.fetch(
        datetime(2026, 4, 12, tzinfo=timezone.utc),
        datetime(2026, 4, 14, tzinfo=timezone.utc),
    )
    assert res.error is None
    assert res.events == []


def test_connector_severity_from_priority():
    assert TechTrendConnector._severity_from_priority("high") == "high"
    assert TechTrendConnector._severity_from_priority("높음") == "high"
    assert TechTrendConnector._severity_from_priority("") is None
    assert TechTrendConnector._severity_from_priority("Unknown") is None
