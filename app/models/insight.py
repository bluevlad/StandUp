"""
Insight Newsletter (v2) 모델

- IngestionEvent: 외부 소스(LogAnalyzer / GitHub Issues / Auto-Tobe)에서 수집된 이벤트
- Newsletter: 합성된 뉴스레터 본문
- NewsletterChunk: pgvector RAG 코퍼스
"""

import uuid

from sqlalchemy import (
    BigInteger, Column, Date, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # pgvector 미설치 환경에서도 import 가능하도록
    Vector = None  # type: ignore

from ..core.database import Base


class IngestionEvent(Base):
    """수집된 외부 이벤트 — 모든 source 의 통합 색인."""
    __tablename__ = "ingestion_events"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", "content_hash",
                         name="uq_ingest_source_dedup"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                server_default=func.gen_random_uuid())
    source_type = Column(String(40), nullable=False)
    source_id = Column(String(300), nullable=False)
    source_url = Column(Text, nullable=True)
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    service_tag = Column(String(80), nullable=True)
    severity = Column(String(20), nullable=True)
    category = Column(String(80), nullable=True)
    title = Column(String(500), nullable=True)
    content_hash = Column(String(64), nullable=False)
    canonical = Column(JSONB, nullable=False, default=dict)
    raw_excerpt = Column(Text, nullable=True)


class Newsletter(Base):
    """발송된(또는 발송 대기 중인) 뉴스레터 본문."""
    __tablename__ = "newsletters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                server_default=func.gen_random_uuid())
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sent_at = Column(DateTime(timezone=True), nullable=True)
    subject = Column(String(500), nullable=False)
    headline = Column(String(1000), nullable=False)
    html_body = Column(Text, nullable=False)
    plain_summary = Column(Text, nullable=False)
    source_event_ids = Column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list,
                              server_default="{}")
    kpis = Column(JSONB, nullable=False, default=dict, server_default="{}")
    synthesis_meta = Column(JSONB, nullable=False, default=dict, server_default="{}")


class NewsletterChunk(Base):
    """pgvector RAG 청크. collection 으로 코퍼스 분리."""
    __tablename__ = "newsletter_chunks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    collection = Column(String(40), nullable=False)
    event_id = Column(UUID(as_uuid=True),
                      ForeignKey("ingestion_events.id", ondelete="CASCADE"),
                      nullable=True)
    newsletter_id = Column(UUID(as_uuid=True),
                           ForeignKey("newsletters.id", ondelete="CASCADE"),
                           nullable=True)
    chunk_text = Column(Text, nullable=False)
    metadata_json = Column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # embedding 은 마이그레이션에서 raw SQL 로 추가 — Vector 가 없는 환경 대비
    if Vector is not None:
        embedding = Column(Vector(768), nullable=True)

    event = relationship("IngestionEvent", lazy="joined", foreign_keys=[event_id])


class HopenVisionProposal(Base):
    """토픽 클러스터 → HopenVision 적용 LLM 제안 (PR3).

    DevPlan 자동 초안화 전 단계의 캐시. status 가 'accepted' 가 되면
    dev_plan_id 가 채워진다.
    """
    __tablename__ = "hopenvision_proposals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                server_default=func.gen_random_uuid())
    cluster_key = Column(String(40), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    model = Column(String(80), nullable=False)
    status = Column(String(20), nullable=False, default="generated",
                    server_default="generated")  # generated|accepted|failed
    cluster_keywords = Column(ARRAY(String), nullable=False, default=list,
                              server_default="{}")
    diagnosis = Column(Text, nullable=True)
    candidate_modules = Column(JSONB, nullable=False, default=list, server_default="[]")
    risks = Column(JSONB, nullable=False, default=list, server_default="[]")
    priority = Column(String(10), nullable=True)
    raw_response = Column(Text, nullable=True)
    eval_ms = Column(Integer, nullable=True)
    dev_plan_id = Column(Integer, ForeignKey("dev_plans.id", ondelete="SET NULL"),
                         nullable=True, index=True)


# Collection 상수
COLLECTION_QA = "corpus_qa"
COLLECTION_LOGS = "corpus_logs"
COLLECTION_FIXES = "corpus_fixes"
COLLECTION_NEWSLETTERS = "corpus_newsletters"

# Source type 상수
SOURCE_LOGANALYZER = "loganalyzer"
SOURCE_GITHUB_QA = "github_qa"
SOURCE_AUTO_TOBE_JOURNAL = "auto_tobe_journal"
SOURCE_AUTO_TOBE_COMMIT = "auto_tobe_commit"
