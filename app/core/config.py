"""
StandUp 설정 관리 모듈
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


APP_VERSION = "0.3.0"

# 한국 표준시 (UTC+9)
KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    """현재 한국 표준시 반환 (timezone-aware)"""
    return datetime.now(KST)


class Settings(BaseSettings):
    """애플리케이션 설정"""

    # 프로젝트 경로
    BASE_DIR: Path = Path(__file__).parent.parent.parent

    # 데이터베이스
    database_url: str = Field(
        default="postgresql://localhost:5432/standup",
        env="DATABASE_URL"
    )

    # Gmail SMTP
    gmail_address: str = Field(default="", env="GMAIL_ADDRESS")
    gmail_app_password: str = Field(default="", env="GMAIL_APP_PASSWORD")

    # 이메일 수신자 (콤마 구분)
    report_recipients: str = Field(default="", env="REPORT_RECIPIENTS")

    # GitHub
    github_token: str = Field(default="", env="GITHUB_TOKEN")
    github_org: str = Field(default="", env="GITHUB_ORG")

    # 스케줄러 - 일일보고 (매일 17:00)
    daily_report_hour: int = Field(default=17, env="DAILY_REPORT_HOUR")
    daily_report_minute: int = Field(default=0, env="DAILY_REPORT_MINUTE")

    # 스케줄러 - 주간보고 (금요일 10:00)
    weekly_report_hour: int = Field(default=10, env="WEEKLY_REPORT_HOUR")
    weekly_report_minute: int = Field(default=0, env="WEEKLY_REPORT_MINUTE")

    # 스케줄러 - 월간보고 (마지막주 금요일 11:00)
    monthly_report_hour: int = Field(default=11, env="MONTHLY_REPORT_HOUR")
    monthly_report_minute: int = Field(default=0, env="MONTHLY_REPORT_MINUTE")

    # Newsletter report display
    max_projects_per_category: int = Field(default=5, env="MAX_PROJECTS_PER_CATEGORY")
    max_items_per_project: int = Field(default=3, env="MAX_ITEMS_PER_PROJECT")

    # ──────────────────────────────────────────────────────────────────────
    # Insight Newsletter (v2) — exaone3.5 cascade
    # ──────────────────────────────────────────────────────────────────────
    # 모드: legacy (기존 일/주/월) | insight (신규 주간 뉴스레터) | both (병행)
    standup_mode: str = Field(default="both", env="STANDUP_MODE")

    # Ollama (host에 설치된 모델 호출 — Docker 컨테이너에서 host.docker.internal 사용)
    ollama_base_url: str = Field(default="http://host.docker.internal:11434", env="OLLAMA_BASE_URL")
    ollama_model_summarize: str = Field(default="llama3.2:3b", env="OLLAMA_MODEL_SUMMARIZE")
    ollama_model_analyze: str = Field(default="qwen2.5-coder:14b", env="OLLAMA_MODEL_ANALYZE")
    ollama_model_compose: str = Field(default="exaone3.5:7.8b", env="OLLAMA_MODEL_COMPOSE")
    ollama_model_embed: str = Field(default="nomic-embed-text", env="OLLAMA_MODEL_EMBED")
    ollama_embed_dim: int = Field(default=768, env="OLLAMA_EMBED_DIM")
    ollama_timeout_sec: int = Field(default=600, env="OLLAMA_TIMEOUT_SEC")

    # Insight 스케줄 (월요일 09:00)
    insight_weekly_dow: str = Field(default="mon", env="INSIGHT_WEEKLY_DOW")
    insight_weekly_hour: int = Field(default=9, env="INSIGHT_WEEKLY_HOUR")
    insight_weekly_minute: int = Field(default=0, env="INSIGHT_WEEKLY_MINUTE")

    # Ingestion 소스
    loganalyzer_base_url: str = Field(default="http://host.docker.internal:9092", env="LOGANALYZER_BASE_URL")
    loganalyzer_enabled: bool = Field(default=True, env="LOGANALYZER_ENABLED")
    # 콤마 구분 — 합성·집계에서 제외할 service_group (대소문자 무관 매칭)
    loganalyzer_exclude_services: str = Field(
        default="InfraWatcher", env="LOGANALYZER_EXCLUDE_SERVICES",
    )
    github_qa_enabled: bool = Field(default=False, env="GITHUB_QA_ENABLED")
    github_qa_repos: str = Field(default="", env="GITHUB_QA_REPOS")  # "owner/repo,owner/repo"
    github_qa_label: str = Field(default="qa-agent", env="GITHUB_QA_LABEL")
    auto_tobe_enabled: bool = Field(default=False, env="AUTO_TOBE_ENABLED")
    auto_tobe_journal_glob: str = Field(default="", env="AUTO_TOBE_JOURNAL_GLOB")  # 예: /work/*/AUTO_TOBE_*.md
    auto_tobe_git_repos: str = Field(default="", env="AUTO_TOBE_GIT_REPOS")  # ":" 구분 로컬 경로

    # Tech Trend (Medium Daily Digest 리포트 + Google/Naver 뉴스 검색)
    tech_trend_enabled: bool = Field(default=False, env="TECH_TREND_ENABLED")
    tech_trend_keywords: str = Field(
        default="java,spring,react", env="TECH_TREND_KEYWORDS",
    )  # 콤마 구분 — 뉴스 검색 키워드, 디지스트 결과 키워드 필터에도 사용
    medium_digest_reports_dir: str = Field(
        default="", env="MEDIUM_DIGEST_REPORTS_DIR",
    )  # 예: /Users/rainend/GIT/medium-digest-agent/reports
    tech_news_max_per_keyword: int = Field(default=5, env="TECH_NEWS_MAX_PER_KEYWORD")
    tech_news_workers: int = Field(default=4, env="TECH_NEWS_WORKERS")
    tech_news_timeout_sec: int = Field(default=15, env="TECH_NEWS_TIMEOUT_SEC")

    # 주간 합성 직후 tech_topics 에 대해 HopenVision 제안 + DevPlan 자동 초안화
    tech_trend_auto_dev_plan: bool = Field(
        default=True, env="TECH_TREND_AUTO_DEV_PLAN",
    )
    tech_trend_max_topics_per_run: int = Field(
        default=3, env="TECH_TREND_MAX_TOPICS_PER_RUN",
    )

    # Naver News API (선택 — 미설정 시 Google News RSS 만 사용)
    naver_client_id: str = Field(default="", env="NAVER_CLIENT_ID")
    naver_client_secret: str = Field(default="", env="NAVER_CLIENT_SECRET")

    # 합성 윈도우
    insight_window_days: int = Field(default=7, env="INSIGHT_WINDOW_DAYS")
    insight_subject_prefix: str = Field(default="[StandUp Insight]", env="INSIGHT_SUBJECT_PREFIX")

    # 로깅
    log_level: str = Field(default="INFO", env="LOG_LEVEL")

    # API
    api_port: int = Field(default=9060, env="API_PORT")
    root_path: str = Field(default="", env="ROOT_PATH")

    @property
    def loganalyzer_excluded_services(self) -> set[str]:
        return {s.strip().lower() for s in self.loganalyzer_exclude_services.split(",") if s.strip()}

    @property
    def github_qa_repo_list(self) -> list[str]:
        return [r.strip() for r in self.github_qa_repos.split(",") if r.strip()]

    @property
    def auto_tobe_git_repo_list(self) -> list[str]:
        return [r.strip() for r in self.auto_tobe_git_repos.split(":") if r.strip()]

    @property
    def tech_trend_keyword_list(self) -> list[str]:
        return [k.strip() for k in self.tech_trend_keywords.split(",") if k.strip()]

    @property
    def is_insight_mode(self) -> bool:
        return self.standup_mode in ("insight", "both")

    @property
    def is_legacy_mode(self) -> bool:
        return self.standup_mode in ("legacy", "both")

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
