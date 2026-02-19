"""
StandUp 설정 관리 모듈
"""

from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    """애플리케이션 설정"""

    # 프로젝트 경로
    BASE_DIR: Path = Path(__file__).parent.parent.parent

    # 데이터베이스
    database_url: str = Field(
        default="postgresql://postgres:postgres123@172.30.1.72:5432/standup_dev",
        env="DATABASE_URL"
    )

    # Gmail SMTP
    gmail_address: str = Field(default="", env="GMAIL_ADDRESS")
    gmail_app_password: str = Field(default="", env="GMAIL_APP_PASSWORD")

    # 이메일 수신자 (콤마 구분)
    report_recipients: str = Field(default="", env="REPORT_RECIPIENTS")

    # GitHub
    github_token: str = Field(default="", env="GITHUB_TOKEN")
    github_org: str = Field(default="bluevlad", env="GITHUB_ORG")

    # 스케줄러 - 일일보고 (매일 17:00)
    daily_report_hour: int = Field(default=17, env="DAILY_REPORT_HOUR")
    daily_report_minute: int = Field(default=0, env="DAILY_REPORT_MINUTE")

    # 스케줄러 - 주간보고 (금요일 10:00)
    weekly_report_hour: int = Field(default=10, env="WEEKLY_REPORT_HOUR")
    weekly_report_minute: int = Field(default=0, env="WEEKLY_REPORT_MINUTE")

    # 스케줄러 - 월간보고 (마지막주 금요일 11:00)
    monthly_report_hour: int = Field(default=11, env="MONTHLY_REPORT_HOUR")
    monthly_report_minute: int = Field(default=0, env="MONTHLY_REPORT_MINUTE")

    # 로깅
    log_level: str = Field(default="INFO", env="LOG_LEVEL")

    # API
    api_port: int = Field(default=9060, env="API_PORT")

    @property
    def recipient_list(self) -> list[str]:
        """수신자 목록 반환"""
        if not self.report_recipients:
            return []
        return [r.strip() for r in self.report_recipients.split(",") if r.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """설정 싱글톤 반환"""
    return Settings()


settings = get_settings()
