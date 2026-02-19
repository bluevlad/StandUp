"""
보고서 및 보고서 항목 모델
"""

import enum
from datetime import datetime

from sqlalchemy import String, Text, Integer, DateTime, Enum, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base


class ReportType(str, enum.Enum):
    """보고서 유형"""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ReportStatus(str, enum.Enum):
    """보고서 상태"""
    GENERATED = "generated"
    SENT = "sent"
    FAILED = "failed"


class Report(Base):
    """보고서 테이블"""
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 보고서 유형/상태
    report_type: Mapped[ReportType] = mapped_column(
        Enum(ReportType), nullable=False
    )
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus), default=ReportStatus.GENERATED, nullable=False
    )

    # 보고 기간
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # 이메일 정보
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    recipients: Mapped[str] = mapped_column(String(1000), nullable=False)
    content_html: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 발송 정보
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 타임스탬프
    generated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 관계
    items: Mapped[list["ReportItem"]] = relationship(
        "ReportItem", back_populates="report", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Report(id={self.id}, type={self.report_type}, status={self.status})>"


class ReportItem(Base):
    """보고서 항목 테이블"""
    __tablename__ = "report_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 보고서 참조
    report_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reports.id", ondelete="CASCADE"), nullable=False
    )

    # 항목 분류
    category: Mapped[str] = mapped_column(String(50), nullable=False)

    # 내용
    project_name: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 출처
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # 관계
    report: Mapped["Report"] = relationship("Report", back_populates="items")

    def __repr__(self) -> str:
        return f"<ReportItem(id={self.id}, category={self.category}, title={self.title[:30]})>"
