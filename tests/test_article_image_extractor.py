"""article_image_extractor 단위 테스트 (PR5).

requests 네트워크 호출은 모킹 — og/twitter/canonical 파싱 로직만 검증.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.article_image_extractor import (
    ArticleMeta,
    _parse_meta,
    extract_article_meta,
    extract_many,
)


# ── _parse_meta 단위 ─────────────────────────────────────────────────────

def test_parse_meta_og_full():
    html = '''
    <html><head>
      <meta property="og:title" content="Spring Boot 3.4 출시">
      <meta property="og:image" content="https://example.com/cover.png">
      <meta property="og:description" content="새 기능 요약">
      <meta property="og:url" content="https://example.com/article/123">
      <meta property="og:site_name" content="DevBlog">
      <link rel="canonical" href="https://example.com/article/123">
    </head></html>
    '''
    m = _parse_meta(html, "https://example.com/article/123?utm=foo")
    assert m.title == "Spring Boot 3.4 출시"
    assert m.image_url == "https://example.com/cover.png"
    assert m.description == "새 기능 요약"
    assert m.site_name == "DevBlog"
    assert m.canonical_url == "https://example.com/article/123"


def test_parse_meta_reverse_attribute_order():
    """content 가 property 앞에 오는 케이스도 흡수."""
    html = '<meta content="https://x.com/img.png" property="og:image">'
    m = _parse_meta(html, "https://x.com")
    assert m.image_url == "https://x.com/img.png"


def test_parse_meta_twitter_fallback():
    html = '''
    <meta name="twitter:image" content="https://t.co/img.jpg">
    <meta name="twitter:title" content="T title">
    '''
    m = _parse_meta(html, "https://t.co/a")
    assert m.image_url == "https://t.co/img.jpg"
    assert m.title == "T title"


def test_parse_meta_no_meta_returns_empty():
    m = _parse_meta("<html><body>no meta</body></html>", "https://x.com")
    assert m.image_url is None
    assert m.title is None


# ── extract_article_meta — requests 모킹 ────────────────────────────────

def _mock_response(body: bytes, status: int = 200, final_url: str = ""):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.status_code = status
    resp.url = final_url
    resp.raw.read = MagicMock(return_value=body)
    return resp


def test_extract_article_meta_invalid_url():
    m = extract_article_meta("not-a-url")
    assert m.fetched is False
    assert "invalid" in (m.error or "").lower()


def test_extract_article_meta_network_failure():
    import requests
    with patch("app.services.article_image_extractor.requests.Session") as sess_cls:
        inst = sess_cls.return_value
        inst.get.side_effect = requests.RequestException("dns fail")
        m = extract_article_meta("https://example.com/a")
    assert m.fetched is False
    assert m.image_url is None
    assert "dns" in (m.error or "")


def test_extract_article_meta_happy_path():
    body = b'<meta property="og:image" content="https://x/img.png">'
    with patch("app.services.article_image_extractor.requests.Session") as sess_cls:
        inst = sess_cls.return_value
        inst.get.return_value = _mock_response(body, final_url="https://x/a")
        m = extract_article_meta("https://x/a?utm=1")
    assert m.fetched is True
    assert m.image_url == "https://x/img.png"


def test_extract_many_respects_limit():
    body = b'<meta property="og:image" content="https://x/img.png">'
    with patch("app.services.article_image_extractor.requests.Session") as sess_cls:
        inst = sess_cls.return_value.__enter__.return_value
        inst.get.return_value = _mock_response(body)
        results = extract_many(
            ["https://x/a", "https://x/b", "https://x/c", "https://x/d"],
            limit=2,
        )
    assert len(results) == 2
