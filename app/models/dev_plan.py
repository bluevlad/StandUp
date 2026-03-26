"""
개발 플랜 및 플랜 항목 모델
- 프로젝트별 개발 계획의 진행률/완료율/품질평가율 추적
"""

import enum
from datetime import datetime

from sqlalchemy import String, Text, Integer, Float, DateTime, Enum, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base


class PlanStatus(str, enum.Enum):
    """플랜 상태"""
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class PlanItemStatus(str, enum.Enum):
    """플랜 항목 상태"""
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"


class PlanItemPriority(str, enum.Enum):
    """플랜 항목 우선순위"""
    P0 = "P0"  # Critical
    P1 = "P1"  # High
    P2 = "P2"  # Medium
    P3 = "P3"  # Low


class DevPlan(Base):
    """개발 플랜 테이블"""
    __tablename__ = "dev_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 프로젝트 연동
    project_name: Mapped[str] = mapped_column(String(200), nullable=False)
    github_repo: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # 플랜 정보
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[PlanStatus] = mapped_column(
        Enum(PlanStatus), default=PlanStatus.ACTIVE, nullable=False
    )

    # Phase 관리
    total_phases: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    current_phase: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # 산출 메트릭 (캐시)
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    completion_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # 일정
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    target_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 타임스탬프
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # 관계
    items: Mapped[list["DevPlanItem"]] = relationship(
        "DevPlanItem", back_populates="plan", cascade="all, delete-orphan",
        order_by="DevPlanItem.phase, DevPlanItem.sort_order"
    )

    def __repr__(self) -> str:
        return f"<DevPlan(id={self.id}, project={self.project_name}, title={self.title[:30]})>"


class DevPlanItem(Base):
    """개발 플랜 항목 테이블"""
    __tablename__ = "dev_plan_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 플랜 참조
    plan_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dev_plans.id", ondelete="CASCADE"), nullable=False
    )

    # Phase / 정렬
    phase: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    phase_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 항목 정보
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[PlanItemPriority] = mapped_column(
        Enum(PlanItemPriority), default=PlanItemPriority.P2, nullable=False
    )
    status: Mapped[PlanItemStatus] = mapped_column(
        Enum(PlanItemStatus), default=PlanItemStatus.TODO, nullable=False
    )

    # 가중치 & 진행률
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # 품질 지표
    has_tests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)       # 0 or 1
    has_review: Mapped[int] = mapped_column(Integer, default=0, nullable=False)      # 0 or 1
    has_docs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)        # 0 or 1
    bug_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # GitHub 연결
    linked_issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    linked_issue_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    linked_commits: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 타임스탬프
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 관계
    plan: Mapped["DevPlan"] = relationship("DevPlan", back_populates="items")

    def __repr__(self) -> str:
        return f"<DevPlanItem(id={self.id}, phase={self.phase}, title={self.title[:30]})>"
