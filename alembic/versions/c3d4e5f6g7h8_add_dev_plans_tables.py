"""add dev_plans and dev_plan_items tables

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-03-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6g7h8'
down_revision: Union[str, None] = 'b2c3d4e5f6g7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # DevPlan 테이블
    op.create_table('dev_plans',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('project_name', sa.String(length=200), nullable=False),
        sa.Column('github_repo', sa.String(length=200), nullable=True),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.Enum('DRAFT', 'ACTIVE', 'COMPLETED', 'ARCHIVED', name='planstatus'), nullable=False),
        sa.Column('total_phases', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('current_phase', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('progress_pct', sa.Float(), nullable=False, server_default='0'),
        sa.Column('completion_pct', sa.Float(), nullable=False, server_default='0'),
        sa.Column('quality_score', sa.Float(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('target_date', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # DevPlanItem 테이블
    op.create_table('dev_plan_items',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('plan_id', sa.Integer(), nullable=False),
        sa.Column('phase', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('phase_title', sa.String(length=200), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('priority', sa.Enum('P0', 'P1', 'P2', 'P3', name='planitempriority'), nullable=False),
        sa.Column('status', sa.Enum('TODO', 'IN_PROGRESS', 'REVIEW', 'DONE', name='planitemstatus'), nullable=False),
        sa.Column('weight', sa.Float(), nullable=False, server_default='1'),
        sa.Column('progress_pct', sa.Float(), nullable=False, server_default='0'),
        sa.Column('has_tests', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('has_review', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('has_docs', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('bug_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('linked_issue_number', sa.Integer(), nullable=True),
        sa.Column('linked_issue_url', sa.String(length=500), nullable=True),
        sa.Column('linked_commits', sa.Text(), nullable=True),
        sa.Column('linked_pr_number', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['plan_id'], ['dev_plans.id'], name='fk_dev_plan_items_dev_plans', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('dev_plan_items')
    op.drop_table('dev_plans')
    # Enum 타입 제거
    sa.Enum(name='planitemstatus').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='planitempriority').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='planstatus').drop(op.get_bind(), checkfirst=True)
