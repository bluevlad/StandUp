"""add diagram_mermaid/case_studies/code_hints to hopenvision_proposals (PR5)

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2026-05-12 01:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, None] = "f6g7h8i9j0k1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hopenvision_proposals",
        sa.Column("diagram_mermaid", sa.Text(), nullable=True),
    )
    op.add_column(
        "hopenvision_proposals",
        sa.Column(
            "case_studies",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "hopenvision_proposals",
        sa.Column(
            "code_hints",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("hopenvision_proposals", "code_hints")
    op.drop_column("hopenvision_proposals", "case_studies")
    op.drop_column("hopenvision_proposals", "diagram_mermaid")
