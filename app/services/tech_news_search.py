"""기술 동향 뉴스 검색 서비스.

키워드 단위로 외부 뉴스 소스를 동시에 호출해 NewsArticle 리스트를 반환한다.
AllergyInsight 의 google_news_service / naver_news_service 패턴을 차용해
- Google News RSS (별도 키 불필요)
- Naver News API (Client ID/Secret 가 있을 때만)
두 소스의 결과를 sha256(title+url) 로 중복 제거 후 병합한다.

본 모듈은 자체 영속성을 갖지 않으며, 상위 connector 가 결과를
`CanonicalEvent` 로 변환해 IngestionHub 에 넘긴다.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import quote

import feedparser
import requests

from ..core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class NewsArticle:
    title: str
    url: str
    source: str            # "google" | "naver"
    description: str
    published_at: Optional[datetime]
    search_keyword: str

    @property
    def fingerprint(self) -> str:
        """중복 판단용 해시 — title+url 기준."""
        key = f"{self.title.strip().lower()}|{self.url.strip().lower()}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


@dataclass
class KeywordSearchResult:
    keyword: str
    articles: list[NewsArticle] = field(default_factory=list)
    elapsed_ms: float = 0.0
    sources: list[str] = field(default_factory=list)


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_ENTITIES = (
    ("&quot;", '"'), ("&amp;", "&"), ("&lt;", "<"),
    ("&gt;", ">"), ("&apos;", "'"), ("&#39;", "'"),
)


def _strip_html(text: str) -> str:
    if not text:
        return ""
    clean = _HTML_TAG_RE.sub("", text)
    for entity, replacement in _HTML_ENTITIES:
        clean = clean.replace(entity, replacement)
    return clean.strip()


def _parse_rss_date(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except (TypeError, ValueError):
        return None


class GoogleNewsRSS:
    """Google News RSS 검색 (키 불필요)."""

    BASE_URL = "https://news.google.com/rss/search"

    def search(
        self,
        query: str,
        *,
        lang: str = "ko",
        country: str = "KR",
        when: str = "7d",
        max_results: int = 10,
        timeout: int = 15,
    ) -> list[NewsArticle]:
        search_query = f"{query} when:{when}" if when else query
        url = (
            f"{self.BASE_URL}?q={quote(search_query)}"
            f"&hl={lang}&gl={country}&ceid={country}:{lang}"
        )

        try:
            # feedparser 는 자체 fetch 도 가능하나 timeout 제어가 까다로워
            # requests 로 받아 string 을 파싱한다.
            resp = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": "StandUp-TechTrend/1.0"},
            )
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
        except Exception as e:  # noqa: BLE001 — 외부 장애 흡수
            logger.warning("google news RSS 실패 (q=%s): %s", query, e)
            return []

        out: list[NewsArticle] = []
        for entry in feed.entries[:max_results]:
            description = _strip_html(
                entry.get("summary", "") or entry.get("description", "")
            )[:500]
            out.append(NewsArticle(
                title=entry.get("title", ""),
                url=entry.get("link", ""),
                source="google",
                description=description,
                published_at=_parse_rss_date(entry.get("published", "")),
                search_keyword=query,
            ))
        return out


class NaverNewsAPI:
    """Naver News 검색 API — Client ID/Secret 필요."""

    BASE_URL = "https://openapi.naver.com/v1/search/news.json"

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._session = requests.Session()
        self._session.headers.update({
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
            "User-Agent": "StandUp-TechTrend/1.0",
        })

    def search(
        self,
        query: str,
        *,
        display: int = 10,
        sort: str = "date",
        timeout: int = 10,
    ) -> list[NewsArticle]:
        if not self.client_id or not self.client_secret:
            return []
        try:
            resp = self._session.get(
                self.BASE_URL,
                params={
                    "query": query,
                    "display": min(display, 100),
                    "sort": sort,
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            logger.warning("naver news API 실패 (q=%s): %s", query, e)
            return []

        out: list[NewsArticle] = []
        for item in data.get("items", []):
            out.append(NewsArticle(
                title=_strip_html(item.get("title", "")),
                url=item.get("link", ""),
                source="naver",
                description=_strip_html(item.get("description", "")),
                published_at=_parse_rss_date(item.get("pubDate", "")),
                search_keyword=query,
            ))
        return out


class TechNewsSearchService:
    """키워드 리스트 → 병렬 검색 → 중복 제거 결과."""

    def __init__(
        self,
        *,
        max_per_keyword: int | None = None,
        workers: int | None = None,
        timeout: int | None = None,
        naver_client_id: str | None = None,
        naver_client_secret: str | None = None,
    ):
        self.max_per_keyword = max_per_keyword or settings.tech_news_max_per_keyword
        self.workers = workers or settings.tech_news_workers
        self.timeout = timeout or settings.tech_news_timeout_sec
        self.google = GoogleNewsRSS()
        self.naver = NaverNewsAPI(
            client_id=(naver_client_id if naver_client_id is not None
                       else settings.naver_client_id),
            client_secret=(naver_client_secret if naver_client_secret is not None
                           else settings.naver_client_secret),
        )

    def search_one(self, keyword: str) -> KeywordSearchResult:
        started = time.time()
        sources: list[str] = []
        articles: list[NewsArticle] = []
        seen: set[str] = set()

        google_articles = self.google.search(
            keyword,
            max_results=self.max_per_keyword,
            timeout=self.timeout,
        )
        if google_articles:
            sources.append("google")
        for a in google_articles:
            fp = a.fingerprint
            if fp in seen:
                continue
            seen.add(fp)
            articles.append(a)

        naver_articles = self.naver.search(
            keyword,
            display=self.max_per_keyword,
            timeout=self.timeout,
        )
        if naver_articles:
            sources.append("naver")
        for a in naver_articles:
            fp = a.fingerprint
            if fp in seen:
                continue
            seen.add(fp)
            articles.append(a)

        return KeywordSearchResult(
            keyword=keyword,
            articles=articles,
            elapsed_ms=(time.time() - started) * 1000,
            sources=sources,
        )

    def search_many(self, keywords: list[str]) -> dict[str, KeywordSearchResult]:
        """키워드 리스트 병렬 검색 → 키워드별 결과 매핑."""
        if not keywords:
            return {}

        results: dict[str, KeywordSearchResult] = {}
        # ThreadPoolExecutor 의 워커 수는 keywords 수보다 클 필요 없음
        max_workers = max(1, min(self.workers, len(keywords)))
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(self.search_one, kw): kw for kw in keywords}
            for fut in as_completed(futures):
                kw = futures[fut]
                try:
                    results[kw] = fut.result(timeout=self.timeout * 2)
                except Exception as e:  # noqa: BLE001
                    logger.warning("tech news search 키워드=%s 실패: %s", kw, e)
                    results[kw] = KeywordSearchResult(keyword=kw)
        return results
