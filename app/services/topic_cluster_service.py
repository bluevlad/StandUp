"""
Topic Cluster Service — pgvector cosine 거리 기반 단순 클러스터링.

- 최근 N일 ingestion 청크(corpus_qa/logs/fixes)를 가져와 pairwise <=> 거리로
  threshold 미만 쌍을 union-find 로 묶는다.
- 클러스터당 키워드(타이틀/카테고리 토큰 빈도) + 이벤트 메타 + 대표 청크 산출.
- 외부 의존(numpy/sklearn) 없이 pgvector 의 SQL 연산자만 사용.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models.insight import (
    COLLECTION_QA, COLLECTION_LOGS, COLLECTION_FIXES, COLLECTION_NEWSLETTERS,
)

logger = logging.getLogger(__name__)

# 한·영 stopword (TF 키워드 추출용)
_STOP = {
    # English
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "of", "to", "in", "for", "on", "at", "by", "and", "or", "with", "from",
    "as", "that", "this", "it", "its", "but", "not", "have", "has", "had",
    "do", "does", "did", "can", "could", "should", "would", "will", "may",
    "error", "errors", "log", "logs", "issue", "issues",
    # Korean (very short list — 자주 쓰이는 비-명사)
    "있다", "없다", "있는", "없는", "이다", "되다", "되는", "위해", "위한",
    "대한", "하지", "하는", "해서", "에서", "으로", "이는", "그리고", "또는",
}

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{2,}|[가-힣]{2,}")


def _tokenize(s: Optional[str]) -> list[str]:
    if not s:
        return []
    out = []
    for m in _TOKEN_RE.findall(s):
        low = m.lower()
        if low in _STOP:
            continue
        out.append(m if any(c.isupper() for c in m) else low)
    return out


def _top_keywords(texts: list[str], k: int = 5) -> list[str]:
    counter: Counter[str] = Counter()
    for t in texts:
        counter.update(_tokenize(t))
    return [w for w, _ in counter.most_common(k)]


@dataclass
class ClusterEvent:
    event_id: str
    title: Optional[str]
    severity: Optional[str]
    category: Optional[str]
    service_tag: Optional[str]
    source_type: Optional[str]
    source_url: Optional[str]
    occurred_at: datetime


@dataclass
class TopicCluster:
    cluster_key: str  # 안정적인 클러스터 식별자 — 대표 chunk_id 사용
    keywords: list[str]
    event_count: int
    chunk_count: int
    first_seen: datetime
    last_seen: datetime
    severity_mix: dict[str, int]
    events: list[ClusterEvent] = field(default_factory=list)


def get_topic_clusters(
    session: Session,
    days: int = 30,
    distance_threshold: float = 0.35,
    min_cluster_size: int = 3,
    max_clusters: int = 10,
    max_chunks: int = 300,
) -> list[TopicCluster]:
    """최근 days 일 동안 수집된 이벤트 청크들을 cosine 거리로 단일-링크 클러스터링."""
    fetch_sql = text("""
        SELECT
            c.id AS chunk_id,
            c.event_id,
            c.chunk_text,
            e.title, e.category, e.severity, e.service_tag,
            e.source_type, e.source_url, e.occurred_at
        FROM newsletter_chunks c
        JOIN ingestion_events e ON e.id = c.event_id
        WHERE c.embedding IS NOT NULL
          AND c.collection IN (:c_qa, :c_logs, :c_fixes)
          AND e.occurred_at >= NOW() - make_interval(days => :days)
        ORDER BY e.occurred_at DESC
        LIMIT :limit
    """)
    rows = session.execute(fetch_sql, {
        "c_qa": COLLECTION_QA,
        "c_logs": COLLECTION_LOGS,
        "c_fixes": COLLECTION_FIXES,
        "days": days,
        "limit": max_chunks,
    }).mappings().all()

    if len(rows) < min_cluster_size:
        logger.info("topic_cluster: 청크 부족 — %d < min_size=%d", len(rows), min_cluster_size)
        return []

    chunk_ids = [r["chunk_id"] for r in rows]
    by_id = {r["chunk_id"]: r for r in rows}

    # pairwise distance — pgvector <=> 인덱스 활용
    pair_sql = text("""
        SELECT a.id AS a_id, b.id AS b_id,
               (a.embedding <=> b.embedding) AS dist
        FROM newsletter_chunks a
        JOIN newsletter_chunks b ON a.id < b.id
        WHERE a.id = ANY(:ids) AND b.id = ANY(:ids)
          AND (a.embedding <=> b.embedding) < :threshold
    """)
    pairs = session.execute(pair_sql, {
        "ids": chunk_ids,
        "threshold": distance_threshold,
    }).all()

    # union-find
    parent = {cid: cid for cid in chunk_ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for p in pairs:
        union(p.a_id, p.b_id)

    groups: dict[int, list[int]] = defaultdict(list)
    for cid in chunk_ids:
        groups[find(cid)].append(cid)

    clusters: list[TopicCluster] = []
    for root, member_ids in groups.items():
        if len(member_ids) < min_cluster_size:
            continue
        member_rows = [by_id[m] for m in member_ids]

        # 이벤트 dedup (한 이벤트가 여러 chunk 로 분할될 수 있음)
        seen_events: dict[str, dict] = {}
        for r in member_rows:
            eid = str(r["event_id"]) if r["event_id"] else None
            if eid and eid not in seen_events:
                seen_events[eid] = r

        if len(seen_events) < min_cluster_size:
            continue

        keywords = _top_keywords(
            [r["title"] or "" for r in seen_events.values()] +
            [r["category"] or "" for r in seen_events.values()] +
            [r["service_tag"] or "" for r in seen_events.values()],
            k=5,
        )

        sev_mix: Counter[str] = Counter()
        for r in seen_events.values():
            sev_mix[(r["severity"] or "other").lower()] += 1

        events = sorted(
            (ClusterEvent(
                event_id=eid,
                title=r["title"],
                severity=r["severity"],
                category=r["category"],
                service_tag=r["service_tag"],
                source_type=r["source_type"],
                source_url=r["source_url"],
                occurred_at=r["occurred_at"],
            ) for eid, r in seen_events.items()),
            key=lambda e: e.occurred_at,
            reverse=True,
        )

        clusters.append(TopicCluster(
            cluster_key=str(root),
            keywords=keywords,
            event_count=len(seen_events),
            chunk_count=len(member_ids),
            first_seen=min(e.occurred_at for e in events),
            last_seen=max(e.occurred_at for e in events),
            severity_mix=dict(sev_mix),
            events=events,
        ))

    clusters.sort(key=lambda c: (c.event_count, c.last_seen), reverse=True)
    return clusters[:max_clusters]


@dataclass
class RelatedNewsletter:
    chunk_id: int
    distance: float
    headline: Optional[str]
    period_start: Optional[str]
    period_end: Optional[str]
    excerpt: str


def get_related_newsletters(
    session: Session,
    cluster_key: str,
    top_k: int = 3,
) -> list[RelatedNewsletter]:
    """대표 chunk(=cluster_key) 임베딩으로 corpus_newsletters 유사 청크 top-k."""
    try:
        rep_id = int(cluster_key)
    except ValueError:
        return []

    sql = text("""
        WITH rep AS (
            SELECT embedding FROM newsletter_chunks WHERE id = :rep_id
        )
        SELECT c.id, c.chunk_text, c.metadata_json, c.newsletter_id,
               (c.embedding <=> rep.embedding) AS dist
        FROM newsletter_chunks c, rep
        WHERE c.collection = :coll
          AND c.embedding IS NOT NULL
          AND c.id <> :rep_id
        ORDER BY c.embedding <=> rep.embedding
        LIMIT :k
    """)
    rows = session.execute(sql, {
        "rep_id": rep_id,
        "coll": COLLECTION_NEWSLETTERS,
        "k": top_k,
    }).mappings().all()

    out = []
    for r in rows:
        meta = r["metadata_json"] or {}
        excerpt = (r["chunk_text"] or "")[:240].strip()
        out.append(RelatedNewsletter(
            chunk_id=r["id"],
            distance=float(r["dist"]),
            headline=meta.get("headline"),
            period_start=meta.get("period_start"),
            period_end=meta.get("period_end"),
            excerpt=excerpt,
        ))
    return out
