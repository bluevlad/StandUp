"""
StandUp - 업무관리 자동화 Agent
FastAPI 메인 애플리케이션
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from alembic.config import Config as AlembicConfig
from alembic import command as alembic_command

from .core.config import settings, APP_VERSION
from .core.logging_config import setup_logging
from .core.scheduler import setup_scheduler, shutdown_scheduler
from .api.v1.endpoints import health, reports, work_items, config

# 로깅 설정 (파일 + 콘솔)
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 실행"""
    logger.info("StandUp Agent 시작 (port: %d)", settings.api_port)

    # Alembic 마이그레이션 실행
    try:
        alembic_cfg = AlembicConfig(str(settings.BASE_DIR / "alembic.ini"))
        alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
        alembic_command.upgrade(alembic_cfg, "head")
        logger.info("DB 마이그레이션 완료")
    except Exception as e:
        logger.error(f"DB 마이그레이션 실패: {e}", exc_info=True)
        raise

    # 스케줄러 시작 (+ 초기 Agent 스캔)
    setup_scheduler()

    yield

    shutdown_scheduler()
    logger.info("StandUp Agent 종료")


app = FastAPI(
    title="StandUp",
    description="업무관리 자동화 Agent - Git Issues 기반 업무 수집/분류/보고서 자동 생성",
    version=APP_VERSION,
    lifespan=lifespan,
)

# 라우터 등록
app.include_router(health.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(work_items.router, prefix="/api/v1")
app.include_router(config.router, prefix="/api/v1")


@app.get("/")
def root():
    return {
        "service": "StandUp",
        "version": APP_VERSION,
        "docs": "/docs",
    }
