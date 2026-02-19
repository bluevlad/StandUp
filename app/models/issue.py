"""
업무 항목 (Git Issues 기반) 모델
"""

import enum
from datetime import datetime

from sqlalchemy import String, Text, Integer, DateTime, Enum, func
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class ItemCategory(str, enum.Enum):
    """업무 분류"""
    PLANNED = "planned"          # 예정사항
    REQUIRED = "required"        # 요구사항
    IN_PROGRESS = "in_progress"  # 진행사항


class ItemStatus(str, enum.Enum):
    """업무 상태"""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class WorkItem(Base):
    """업무 항목 테이블"""
    __tablename__ = "work_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # GitHub 연동 정보
    github_repo: Mapped[str] = mapped_column(String(200), nullable=False)
    github_issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    github_issue_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # 업무 분류/상태
    category: Mapped[ItemCategory] = mapped_column(
        Enum(ItemCategory), nullable=False
    )
    status: Mapped[ItemStatus] = mapped_column(
        Enum(ItemStatus), default=ItemStatus.OPEN, nullable=False
    )

    # 내용
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    labels: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # 관련 커밋 (SHA 목록, 콤마 구분)
    related_commits: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 타임스탬프
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<WorkItem(id={self.id}, repo={self.github_repo}, title={self.title[:30]})>"
