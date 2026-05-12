"""medium-digest-agent v2 출력 포맷 파싱 단위 테스트 (PR-SU-11).

PR-MDA-2 (importance_score + factors), PR-MDA-3 (interpretation 섹션) 가 추가한
markdown 필드를 MediumDigestReaderService.parse_report 가 정상 흡수하는지 검증.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.medium_digest_reader import parse_report


V2_REPORT = """\
# [Spring Boot REST Clients] 적용 제안 — hopenvision

## 요약
- **기술 키워드**: Spring Boot REST Clients
- **카테고리**: api-design
- **출처 뉴스레터**: Spring Boot 4 Just Made REST Calls Super Easy!
- **분석일**: 2026-05-12
- **우선순위**: medium
- **도입 난이도**: low
- **기술 성숙도**: mainstream
- **중요도 점수**: 78/100
- **점수 근거**:
  - mainstream 채택, Spring Boot 4 정식 발표
  - api 도메인 직접 매핑 가능
  - 학습 곡선 낮음
  - 기존 RestTemplate 마이그레이션 부담 일부 존재

## 제목 의미 해석
**핵심 메시지**: Spring Boot 4 가 RestClient 도입으로 REST 호출 코드를 단순화한다.
**왜 지금 화제인가**: Spring 6+ stable 이후 신규 RestClient API 가 RestTemplate 대안으로 확산.
**개발자 Take-away**:
- RestTemplate → RestClient 마이그레이션 패턴 익히기
- 새 API 의 fluent 방식이 가독성·테스트 용이성 향상
- WebClient 와 다른 선택 기준 이해

## 참고 자료
- [Spring 4 RestClient Guide - spring.io](https://spring.io/blog/rc)

## 기술 설명
Spring Boot 4 의 RestClient 는 ...

## 적용 대상
| 모듈 | 변경 |

## 변경 사항
...

## 리스크 및 롤백 전략
...
"""


V1_REPORT = """\
# [Java 21+] 적용 제안 — academy-admin/backend

## 요약
- **기술 키워드**: Java 21+
- **카테고리**: language-features
- **출처 뉴스레터**: Java 25 ...
- **분석일**: 2026-04-13
- **우선순위**: medium
- **도입 난이도**: medium
- **기술 성숙도**: mainstream

## 참고 자료
- [Oracle Releases Java 26](https://news.google.com/foo)

## 기술 설명
Java 21은 ...

## 리스크 및 롤백 전략
- 호환성 이슈
"""


@pytest.fixture()
def v2_file(tmp_path: Path) -> Path:
    p = tmp_path / "2026-05-12-spring-boot-rest-clients.md"
    p.write_text(V2_REPORT, encoding="utf-8")
    return p


@pytest.fixture()
def v1_file(tmp_path: Path) -> Path:
    p = tmp_path / "2026-04-13-java-21.md"
    p.write_text(V1_REPORT, encoding="utf-8")
    return p


def test_parses_importance_score_and_factors(v2_file):
    r = parse_report(v2_file)
    assert r is not None
    assert r.importance_score == 78
    assert len(r.importance_factors) == 4
    assert r.importance_factors[0].startswith("mainstream")


def test_parses_interpretation_section(v2_file):
    r = parse_report(v2_file)
    assert r is not None
    assert "RestClient" in r.interpretation_core
    assert "Spring 6" in r.interpretation_why
    assert len(r.interpretation_takeaways) == 3
    assert any("마이그레이션" in t for t in r.interpretation_takeaways)


def test_v1_report_keeps_new_fields_empty(v1_file):
    """PR-MDA-2/3 이전 포맷 — 신규 필드는 None/빈 리스트/빈 문자열."""
    r = parse_report(v1_file)
    assert r is not None
    assert r.keyword == "Java 21+"
    assert r.importance_score is None
    assert r.importance_factors == []
    assert r.interpretation_core == ""
    assert r.interpretation_why == ""
    assert r.interpretation_takeaways == []


def test_score_clamps_out_of_range(tmp_path):
    body = V2_REPORT.replace("78/100", "250")
    p = tmp_path / "2026-05-12-out.md"
    p.write_text(body, encoding="utf-8")
    r = parse_report(p)
    assert r.importance_score == 100


def test_score_handles_missing_slash(tmp_path):
    """'85' 처럼 /100 없는 형식도 흡수."""
    body = V2_REPORT.replace("78/100", "85")
    p = tmp_path / "2026-05-12-noslash.md"
    p.write_text(body, encoding="utf-8")
    r = parse_report(p)
    assert r.importance_score == 85


def test_interpretation_handles_partial(tmp_path):
    """interpretation 섹션 중 일부 필드만 있어도 안전."""
    body = V2_REPORT.replace(
        "**왜 지금 화제인가**: Spring 6+ stable 이후 신규 RestClient API 가 RestTemplate 대안으로 확산.\n",
        "",
    )
    p = tmp_path / "2026-05-12-partial.md"
    p.write_text(body, encoding="utf-8")
    r = parse_report(p)
    assert r.interpretation_core != ""
    assert r.interpretation_why == ""
    assert len(r.interpretation_takeaways) == 3
