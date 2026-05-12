"""add fitness_score/impact_area/effort_hours to hopenvision_proposals (PR4)

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2026-05-12 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6g7h8i9j0k1"
down_revision: Union[str, None] = "e5f6g7h8i9j0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hopenvision_proposals",
        sa.Column("fitness_score", sa.Integer(), nullable=True),
    )
    op.add_column(
        "hopenvision_proposals",
        sa.Column("impact_area", sa.String(40), nullable=True),
    )
    op.add_column(
        "hopenvision_proposals",
        sa.Column("effort_hours", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_hopenvision_proposals_fitness_score",
        "hopenvision_proposals",
        ["fitness_score"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hopenvision_proposals_fitness_score",
        table_name="hopenvision_proposals",
    )
    op.drop_column("hopenvision_proposals", "effort_hours")
    op.drop_column("hopenvision_proposals", "impact_area")
    op.drop_column("hopenvision_proposals", "fitness_score")
