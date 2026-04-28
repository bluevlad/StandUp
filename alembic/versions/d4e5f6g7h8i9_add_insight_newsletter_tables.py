"""add insight newsletter tables (ingestion_events, newsletter_chunks, newsletters) + pgvector

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-04-28 00:00:00.000000

설계 노트:
- 기존 recipients 테이블을 그대로 활용 (report_types='insight' 행이 v2 수신자)
- 원본 추적 가능: ingestion_events.source_url + newsletter_chunks.event_id
- RAG 컬렉션 분리: corpus_qa / corpus_logs / corpus_fixes / corpus_newsletters
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d4e5f6g7h8i9"
down_revision: Union[str, None] = "c3d4e5f6g7h8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector 확장 (DBA 권한 필요 — 운영 DB에서 사전 활성 가능)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── ingestion_events: 모든 수집 이벤트의 원본 색인 ──────────────────
    op.create_table(
        "ingestion_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", sa.String(300), nullable=False),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("service_tag", sa.String(80), nullable=True),
        sa.Column("severity", sa.String(20), nullable=True),
        sa.Column("category", sa.String(80), nullable=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("canonical", postgresql.JSONB, nullable=False),
        sa.Column("raw_excerpt", sa.Text, nullable=True),
        sa.UniqueConstraint("source_type", "source_id", "content_hash",
                            name="uq_ingest_source_dedup"),
    )
    op.create_index("ix_ingest_occurred", "ingestion_events",
                    [sa.text("occurred_at DESC")])
    op.create_index("ix_ingest_service", "ingestion_events", ["service_tag"])
    op.create_index("ix_ingest_source_type", "ingestion_events", ["source_type"])

    # ── newsletters: 발송 본문 ──────────────────────────────────────────
    op.create_table(
        "newsletters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("headline", sa.String(1000), nullable=False),
        sa.Column("html_body", sa.Text, nullable=False),
        sa.Column("plain_summary", sa.Text, nullable=False),
        sa.Column("source_event_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
                  nullable=False, server_default="{}"),
        sa.Column("kpis", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("synthesis_meta", postgresql.JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("ix_newsletter_period", "newsletters",
                    [sa.text("period_start DESC")])

    # ── newsletter_chunks: pgvector RAG 코퍼스 ──────────────────────────
    op.create_table(
        "newsletter_chunks",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("collection", sa.String(40), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("ingestion_events.id", ondelete="CASCADE"),
                  nullable=True),
        sa.Column("newsletter_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("newsletters.id", ondelete="CASCADE"),
                  nullable=True),
        sa.Column("chunk_text", sa.Text, nullable=False),
        sa.Column("metadata_json", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    # embedding 컬럼은 vector 타입 — Alembic이 모르므로 raw SQL
    op.execute("ALTER TABLE newsletter_chunks ADD COLUMN embedding vector(768)")
    op.create_index("ix_chunks_collection", "newsletter_chunks", ["collection"])
    op.create_index("ix_chunks_event", "newsletter_chunks", ["event_id"])
    # ivfflat 인덱스 — 데이터 쌓인 후 REINDEX 권장 (lists는 sqrt(N) 권장)
    op.execute(
        "CREATE INDEX ix_chunks_embedding ON newsletter_chunks "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    # ── 수신자 시드 (recipients 테이블 재활용) ───────────────────────────
    # report_types='insight' 가 v2 뉴스레터 수신자
    op.execute("""
        INSERT INTO recipients (name, email, report_types, is_active)
        VALUES ('rainend', 'rainend00@gmail.com', 'insight', true)
        ON CONFLICT (email) DO UPDATE
            SET report_types = CASE
                WHEN recipients.report_types = 'all' THEN 'all'
                WHEN recipients.report_types LIKE '%insight%' THEN recipients.report_types
                ELSE recipients.report_types || ',insight'
            END,
            is_active = true
    """)


def downgrade() -> None:
    op.drop_index("ix_chunks_embedding", table_name="newsletter_chunks")
    op.drop_index("ix_chunks_event", table_name="newsletter_chunks")
    op.drop_index("ix_chunks_collection", table_name="newsletter_chunks")
    op.drop_table("newsletter_chunks")

    op.drop_index("ix_newsletter_period", table_name="newsletters")
    op.drop_table("newsletters")

    op.drop_index("ix_ingest_source_type", table_name="ingestion_events")
    op.drop_index("ix_ingest_service", table_name="ingestion_events")
    op.drop_index("ix_ingest_occurred", table_name="ingestion_events")
    op.drop_table("ingestion_events")

    # pgvector 확장은 다른 곳에서 쓸 수 있으므로 DROP 안 함
