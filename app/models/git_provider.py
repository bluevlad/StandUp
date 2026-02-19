"""
Git Provider 모델 - Git 연결 정보 관리
"""

import enum

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum, func
from sqlalchemy.orm import relationship

from ..core.database import Base


class ProviderType(str, enum.Enum):
    """Git 서비스 종류"""
    GITHUB = "github"
    GITLAB = "gitlab"


class GitProvider(Base):
    """Git 프로바이더 (GitHub/GitLab 연결 정보)"""
    __tablename__ = "git_providers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    provider_type = Column(Enum(ProviderType), nullable=False, default=ProviderType.GITHUB)
    base_url = Column(String(500), nullable=True)
    token = Column(String(500), nullable=False)
    org_name = Column(String(200), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationship
    repositories = relationship("Repository", back_populates="git_provider", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<GitProvider(id={self.id}, name='{self.name}', org='{self.org_name}')>"
