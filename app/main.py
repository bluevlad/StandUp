"""
StandUp - 업무관리 자동화 Agent
FastAPI 메인 애플리케이션
"""

import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from alembic.config import Config as AlembicConfig
from alembic import command as alembic_command

from .core.config import settings, APP_VERSION
from .core.logging_config import setup_logging
from .core.scheduler import setup_scheduler, shutdown_scheduler
from .api.v1.endpoints import health, reports, work_items, config, stats, dashboard, dev_plans

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
        # Alembic이 logging.config.fileConfig()로 root logger를 덮어쓰므로 재설정
        setup_logging()
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
    root_path=settings.root_path,
)

# 라우터 등록
app.include_router(health.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(work_items.router, prefix="/api/v1")
app.include_router(config.router, prefix="/api/v1")
app.include_router(stats.router, prefix="/api/v1")
app.include_router(dev_plans.router, prefix="/api/v1")
app.include_router(dashboard.router)

# 서비스 소개 페이지 (intro.html) 라우트
# StaticFiles mount 대신 직접 라우트로 노출 — ROOT_PATH 환경에서 mount는
# root_path가 prepend된 경로만 매칭하지만 라우트는 양쪽 모두 매칭한다.
_intro_static = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
def root():
    return FileResponse(_intro_static / "intro.html")


@app.get("/intro.html", include_in_schema=False)
def intro_page():
    return FileResponse(_intro_static / "intro.html")


@app.get("/css/service-landing.css", include_in_schema=False)
def landing_css():
    return FileResponse(
        _intro_static / "css" / "service-landing.css",
        media_type="text/css",
    )


@app.get("/api/info", include_in_schema=False)
def api_info():
    return {
        "service": "StandUp",
        "version": APP_VERSION,
        "docs": "/docs",
        "intro": "/",
    }
