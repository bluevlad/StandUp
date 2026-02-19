"""
Recipient 모델 - 보고서 수신자 관리
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, func

from ..core.database import Base


class Recipient(Base):
    """보고서 수신자"""
    __tablename__ = "recipients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    email = Column(String(300), nullable=False, unique=True)
    report_types = Column(String(100), default="all", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<Recipient(id={self.id}, name='{self.name}', email='{self.email}')>"
