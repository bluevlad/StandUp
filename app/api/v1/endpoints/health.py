"""
헬스체크 및 모니터링 엔드포인트
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from ....core.database import get_db
from ....core.scheduler import scheduler
from ....models.issue import WorkItem, ItemCategory
from ....models.report import Report, ReportStatus
from ....models.agent_log import AgentLog

router = APIRouter()


@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    """서비스 상태 확인"""
    jobs = scheduler.get_jobs() if scheduler.running else []

    # DB 통계
    work_item_count = db.query(func.count(WorkItem.id)).scalar()
    report_count = db.query(func.count(Report.id)).scalar()

    return {
        "status": "ok",
        "service": "StandUp",
        "version": "0.2.0",
        "timestamp": datetime.now().isoformat(),
        "database": {
            "work_items": work_item_count,
            "reports": report_count,
        },
        "scheduler": {
            "running": scheduler.running,
            "jobs": [
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run": str(job.next_run_time) if job.next_run_time else None,
                }
                for job in jobs
            ],
        },
    }


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    """업무 통계 조회"""
    planned = db.query(func.count(WorkItem.id)).filter(
        WorkItem.category == ItemCategory.PLANNED
    ).scalar()
    required = db.query(func.count(WorkItem.id)).filter(
        WorkItem.category == ItemCategory.REQUIRED
    ).scalar()
    in_progress = db.query(func.count(WorkItem.id)).filter(
        WorkItem.category == ItemCategory.IN_PROGRESS
    ).scalar()

    sent_reports = db.query(func.count(Report.id)).filter(
        Report.status == ReportStatus.SENT
    ).scalar()
    failed_reports = db.query(func.count(Report.id)).filter(
        Report.status == ReportStatus.FAILED
    ).scalar()

    return {
        "work_items": {
            "planned": planned,
            "required": required,
            "in_progress": in_progress,
            "total": planned + required + in_progress,
        },
        "reports": {
            "sent": sent_reports,
            "failed": failed_reports,
        },
    }


@router.get("/agent-logs")
def get_agent_logs(
    agent_name: str = None,
    limit: int = Query(default=20, le=100),
    db: Session = Depends(get_db),
):
    """Agent 실행 이력 조회"""
    query = db.query(AgentLog).order_by(AgentLog.executed_at.desc())
    if agent_name:
        query = query.filter(AgentLog.agent_name == agent_name)
    logs = query.limit(limit).all()

    return [
        {
            "id": log.id,
            "agent_name": log.agent_name,
            "action": log.action,
            "status": log.status,
            "detail": log.detail,
            "items_processed": log.items_processed,
            "duration_seconds": log.duration_seconds,
            "executed_at": log.executed_at.isoformat() if log.executed_at else None,
        }
        for log in logs
    ]
