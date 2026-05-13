"""
Claude Code 세션 로그 모델 (회의록 표준)

- claude_sessions: 세션 메타 + 회의록 본문 (Markdown)
- session_items:   회의 내용 N개 (제목 + 내용)
- session_pending: 미결사항 → work_items 승인 후 연결
- session_commits: 세션 기간 동안 발생한 git 커밋 매핑

표준 양식: Claude-Opus-bluevlad/standards/claude-code/SESSION_LOG_FORMAT.md
"""

import enum
from datetime import datetime

from sqlalchemy import String, Text, Integer, DateTime, Enum, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base


class SessionSource(str, enum.Enum):
    AUTO = "auto"        # Stop hook 자동 등록
    MANUAL = "manual"    # 슬래시 명령어 수동 호출
    HYBRID = "hybrid"    # 자동 등록 후 사용자 보강


class PendingStatus(str, enum.Enum):
    OPEN = "open"              # 추출만 됨, 미승인
    REGISTERED = "registered"  # work_items 로 등록됨
    DISMISSED = "dismissed"    # 사용자가 거절
    RESOLVED = "resolved"      # 후속 처리 완료


class ClaudeSession(Base):
    __tablename__ = "claude_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 세션 식별
    session_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    project_name: Mapped[str] = mapped_column(String(200), nullable=False)
    cwd: Mapped[str | None] = mapped_column(String(500), nullable=True)
    git_branch: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # 회의록 표준 필드
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    document_no: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # 본문
    summary_md: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 메타
    source: Mapped[SessionSource] = mapped_column(
        Enum(SessionSource), default=SessionSource.AUTO, nullable=False
    )
    duration_min: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    commit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    items: Mapped[list["SessionItem"]] = relationship(
        "SessionItem", back_populates="session",
        cascade="all, delete-orphan", order_by="SessionItem.seq"
    )
    pending: Mapped[list["SessionPending"]] = relationship(
        "SessionPending", back_populates="session", cascade="all, delete-orphan"
    )
    commits: Mapped[list["SessionCommit"]] = relationship(
        "SessionCommit", back_populates="session", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ClaudeSession(id={self.id}, project={self.project_name}, topic={self.topic[:30]})>"


class SessionItem(Base):
    __tablename__ = "session_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("claude_sessions.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped["ClaudeSession"] = relationship("ClaudeSession", back_populates="items")


class SessionPending(Base):
    __tablename__ = "session_pending"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("claude_sessions.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[PendingStatus] = mapped_column(
        Enum(PendingStatus), default=PendingStatus.OPEN, nullable=False
    )
    work_item_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    session: Mapped["ClaudeSession"] = relationship("ClaudeSession", back_populates="pending")


class SessionCommit(Base):
    __tablename__ = "session_commits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("claude_sessions.id", ondelete="CASCADE"), nullable=False
    )
    repo: Mapped[str] = mapped_column(String(200), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    commit_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    session: Mapped["ClaudeSession"] = relationship("ClaudeSession", back_populates="commits")
