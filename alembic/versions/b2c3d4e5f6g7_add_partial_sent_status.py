"""add partial_sent to reportstatus enum

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL enum에 새 값 추가
    op.execute("ALTER TYPE reportstatus ADD VALUE IF NOT EXISTS 'PARTIAL_SENT' AFTER 'SENT'")


def downgrade() -> None:
    # PostgreSQL에서는 enum 값 제거가 직접 불가하므로 주의 필요
    # 실제 downgrade 시에는 PARTIAL_SENT → SENT로 데이터 변환 후 enum 재생성 필요
    op.execute("UPDATE reports SET status = 'SENT' WHERE status = 'PARTIAL_SENT'")
