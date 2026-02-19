"""
AppSetting 모델 - 앱 설정 (Key-Value)
"""

from sqlalchemy import Column, Integer, String, DateTime, func

from ..core.database import Base


class AppSetting(Base):
    """앱 설정 (Key-Value 스토어)"""
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), nullable=False, unique=True)
    value = Column(String(1000), nullable=False)
    value_type = Column(String(20), default="string", nullable=False)
    category = Column(String(50), default="general", nullable=False)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<AppSetting(key='{self.key}', value='{self.value}')>"
