"""
StandUp - 업무관리 자동화 Agent
FastAPI 메인 애플리케이션
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .core.config import settings
from .core.database import engine, Base
from .core.logging_config import setup_logging
from .core.scheduler import setup_scheduler, shutdown_scheduler
from .api.v1.endpoints import health, reports, work_items

# 로깅 설정 (파일 + 콘솔)
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 실행"""
    logger.info("StandUp Agent 시작 (port: %d)", settings.api_port)

    # DB 테이블 자동 생성
    from .models import WorkItem, Report, ReportItem, AgentLog  # noqa: F401
    Base.metadata.create_all(bind=engine)
    logger.info("DB 테이블 확인 완료")

    # 스케줄러 시작 (+ 초기 Agent 스캔)
    setup_scheduler()

    yield

    shutdown_scheduler()
    logger.info("StandUp Agent 종료")


app = FastAPI(
    title="StandUp",
    description="업무관리 자동화 Agent - Git Issues 기반 업무 수집/분류/보고서 자동 생성",
    version="0.2.0",
    lifespan=lifespan,
)

# 라우터 등록
app.include_router(health.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(work_items.router, prefix="/api/v1")


@app.get("/")
def root():
    return {
        "service": "StandUp",
        "version": "0.2.0",
        "docs": "/docs",
    }
