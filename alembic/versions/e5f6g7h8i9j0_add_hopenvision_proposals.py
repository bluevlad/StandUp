"""add hopenvision_proposals table (PR3)

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-05-04 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e5f6g7h8i9j0"
down_revision: Union[str, None] = "d4e5f6g7h8i9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hopenvision_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("cluster_key", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="generated"),
        sa.Column("cluster_keywords",
                  postgresql.ARRAY(sa.String()), nullable=False,
                  server_default="{}"),
        sa.Column("diagnosis", sa.Text(), nullable=True),
        sa.Column("candidate_modules", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="[]"),
        sa.Column("risks", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="[]"),
        sa.Column("priority", sa.String(10), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("eval_ms", sa.Integer(), nullable=True),
        sa.Column("dev_plan_id", sa.Integer(),
                  sa.ForeignKey("dev_plans.id", ondelete="SET NULL"),
                  nullable=True),
    )
    op.create_index("ix_hopenvision_proposals_cluster_key",
                    "hopenvision_proposals", ["cluster_key"])
    op.create_index("ix_hopenvision_proposals_dev_plan_id",
                    "hopenvision_proposals", ["dev_plan_id"])


def downgrade() -> None:
    op.drop_index("ix_hopenvision_proposals_dev_plan_id",
                  table_name="hopenvision_proposals")
    op.drop_index("ix_hopenvision_proposals_cluster_key",
                  table_name="hopenvision_proposals")
    op.drop_table("hopenvision_proposals")
