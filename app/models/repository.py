"""
Repository 모델 - 스캔 대상 리포지토리 관리
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship

from ..core.database import Base


class Repository(Base):
    """스캔 대상 리포지토리"""
    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    git_provider_id = Column(
        Integer,
        ForeignKey("git_providers.id", ondelete="CASCADE"),
        nullable=False,
    )
    repo_name = Column(String(200), nullable=False)
    repo_full_name = Column(String(500), nullable=False)
    repo_url = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationship
    git_provider = relationship("GitProvider", back_populates="repositories")

    def __repr__(self):
        return f"<Repository(id={self.id}, name='{self.repo_full_name}')>"
