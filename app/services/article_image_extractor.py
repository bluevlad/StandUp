"""외부 기사 URL 에서 대표 이미지(og:image) + canonical url 추출 (PR5).

뉴스 기사 1건 fetch → HTML 헤더의 OpenGraph/Twitter 메타 + canonical link 만
추출해 반환. 본문은 보지 않으며, requests 단발 호출로 단순 처리.

외부 의존을 늘리지 않기 위해 정규식 기반 — 단, og:* 메타는 단순 구조라
일반적인 사이트에서 충분히 작동한다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# HTML 본문 전체를 받지 않도록 헤더(~16KB) 만으로 충분
_HEAD_FETCH_BYTES = 16 * 1024
_DEFAULT_TIMEOUT = 6
_USER_AGENT = "StandUp-HopenTechBrief/1.0 (+https://github.com/bluevlad/StandUp)"

_RE_META_OG = re.compile(
    r'<meta\s+[^>]*property\s*=\s*[\'"]og:(image|title|description|url|site_name)[\'"][^>]*'
    r'content\s*=\s*[\'"]([^\'"]+)[\'"]',
    re.IGNORECASE,
)
_RE_META_OG_REV = re.compile(
    r'<meta\s+[^>]*content\s*=\s*[\'"]([^\'"]+)[\'"]\s*[^>]*'
    r'property\s*=\s*[\'"]og:(image|title|description|url|site_name)[\'"]',
    re.IGNORECASE,
)
_RE_META_TWITTER = re.compile(
    r'<meta\s+[^>]*name\s*=\s*[\'"]twitter:(image|title|description)[\'"][^>]*'
    r'content\s*=\s*[\'"]([^\'"]+)[\'"]',
    re.IGNORECASE,
)
_RE_LINK_CANONICAL = re.compile(
    r'<link\s+[^>]*rel\s*=\s*[\'"]canonical[\'"][^>]*href\s*=\s*[\'"]([^\'"]+)[\'"]',
    re.IGNORECASE,
)
_RE_CHARSET = re.compile(
    rb'<meta\s+[^>]*charset\s*=\s*["\']?([\w\-]+)', re.IGNORECASE,
)


@dataclass
class ArticleMeta:
    url: str
    canonical_url: Optional[str] = None
    image_url: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    site_name: Optional[str] = None
    fetched: bool = False
    error: Optional[str] = None


def _decode_partial(raw: bytes) -> str:
    """본문 인코딩 추정 후 디코드. 실패 시 utf-8 + replace."""
    m = _RE_CHARSET.search(raw)
    if m:
        try:
            return raw.decode(m.group(1).decode("ascii", "ignore"), errors="replace")
        except (LookupError, UnicodeDecodeError):
            pass
    return raw.decode("utf-8", errors="replace")


def _parse_meta(html: str, base_url: str) -> ArticleMeta:
    """HTML(헤더 부분) → ArticleMeta. og:* / twitter:* / canonical 만 본다."""
    meta = ArticleMeta(url=base_url, fetched=True)

    # og:* 정/역방향 (속성 순서 무관) 매칭
    og_pairs: dict[str, str] = {}
    for m in _RE_META_OG.finditer(html):
        og_pairs.setdefault(m.group(1).lower(), m.group(2).strip())
    for m in _RE_META_OG_REV.finditer(html):
        og_pairs.setdefault(m.group(2).lower(), m.group(1).strip())

    meta.image_url = og_pairs.get("image")
    meta.title = og_pairs.get("title")
    meta.description = og_pairs.get("description")
    meta.site_name = og_pairs.get("site_name")
    if not meta.image_url and not meta.description:
        # twitter:* fallback
        for m in _RE_META_TWITTER.finditer(html):
            key, val = m.group(1).lower(), m.group(2).strip()
            if key == "image" and not meta.image_url:
                meta.image_url = val
            elif key == "title" and not meta.title:
                meta.title = val
            elif key == "description" and not meta.description:
                meta.description = val

    canon = _RE_LINK_CANONICAL.search(html)
    if canon:
        meta.canonical_url = canon.group(1).strip()

    return meta


def extract_article_meta(
    url: str,
    *,
    timeout: int = _DEFAULT_TIMEOUT,
    max_bytes: int = _HEAD_FETCH_BYTES,
    session: Optional[requests.Session] = None,
) -> ArticleMeta:
    """외부 기사 URL → ArticleMeta. 실패 시 fetched=False + error 기록 후 반환."""
    if not url or not url.startswith(("http://", "https://")):
        return ArticleMeta(url=url or "", error="invalid url")

    sess = session or requests.Session()
    if session is None:
        # 신규 세션이면 OrbStack 자동 주입 proxy 우회 — IPv6 resolve 깨짐 회피.
        sess.trust_env = False
    try:
        resp = sess.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ko,en;q=0.8",
            },
            stream=True,
            allow_redirects=True,
        )
        resp.raise_for_status()
        # HEAD 만 읽는다 (본문 전체 X)
        raw = resp.raw.read(max_bytes, decode_content=True) or b""
    except requests.RequestException as e:
        logger.info("article meta fetch 실패 url=%s err=%s", url, e)
        return ArticleMeta(url=url, error=str(e)[:120])
    finally:
        if session is None:
            sess.close()

    if not raw:
        return ArticleMeta(url=url, error="empty body")

    html = _decode_partial(raw)
    meta = _parse_meta(html, base_url=url)

    # 최종 redirect 후 URL 우선
    final_url = getattr(resp, "url", None) or url
    if final_url and final_url != url and not meta.canonical_url:
        meta.canonical_url = final_url

    return meta


def extract_many(
    urls: list[str],
    *,
    timeout: int = _DEFAULT_TIMEOUT,
    limit: int = 5,
) -> list[ArticleMeta]:
    """여러 URL 의 메타를 순차 추출. limit 만큼만 처리."""
    out: list[ArticleMeta] = []
    if not urls:
        return out
    with requests.Session() as sess:
        sess.trust_env = False  # 호스트 proxy 자동 주입 우회
        for url in urls[:limit]:
            out.append(extract_article_meta(url, timeout=timeout, session=sess))
    return out
