"""add claude_sessions, session_items, session_pending, session_commits

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-05-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h8i9j0k1l2m3"
down_revision: Union[str, None] = "g7h8i9j0k1l2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "claude_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=100), nullable=False),
        sa.Column("project_name", sa.String(length=200), nullable=False),
        sa.Column("cwd", sa.String(length=500), nullable=True),
        sa.Column("git_branch", sa.String(length=200), nullable=True),
        sa.Column("topic", sa.String(length=500), nullable=False),
        sa.Column("document_no", sa.String(length=50), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=False),
        sa.Column("summary_md", sa.Text(), nullable=True),
        sa.Column(
            "source",
            sa.Enum("AUTO", "MANUAL", "HYBRID", name="sessionsource"),
            nullable=False,
            server_default="AUTO",
        ),
        sa.Column("duration_min", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("commit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_claude_sessions_session_id"),
        sa.UniqueConstraint("document_no", name="uq_claude_sessions_document_no"),
    )
    op.create_index(
        "ix_claude_sessions_project_started",
        "claude_sessions",
        ["project_name", "started_at"],
    )

    op.create_table(
        "session_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"], ["claude_sessions.id"],
            name="fk_session_items_claude_sessions", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "session_pending",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("OPEN", "REGISTERED", "DISMISSED", "RESOLVED", name="pendingstatus"),
            nullable=False,
            server_default="OPEN",
        ),
        sa.Column("work_item_id", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["claude_sessions.id"],
            name="fk_session_pending_claude_sessions", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["work_item_id"], ["work_items.id"],
            name="fk_session_pending_work_items", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "session_commits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("repo", sa.String(length=200), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=False),
        sa.Column("commit_message", sa.Text(), nullable=True),
        sa.Column("committed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"], ["claude_sessions.id"],
            name="fk_session_commits_claude_sessions", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("session_commits")
    op.drop_table("session_pending")
    op.drop_table("session_items")
    op.drop_index("ix_claude_sessions_project_started", table_name="claude_sessions")
    op.drop_table("claude_sessions")
    sa.Enum(name="pendingstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="sessionsource").drop(op.get_bind(), checkfirst=True)
