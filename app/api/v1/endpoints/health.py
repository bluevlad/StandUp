"""
헬스체크 및 모니터링 엔드포인트
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from ....core.config import APP_VERSION, now_kst
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
        "version": APP_VERSION,
        "timestamp": now_kst().isoformat(),
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


@router.get("/report-diagnosis")
def report_diagnosis(db: Session = Depends(get_db)):
    """보고서 발송 진단 (설정 상태, 최근 발송 이력 확인)"""
    from ....services import config_service
    from ....services.email_service import get_email_service, get_email_service_with_config

    # 1. Gmail 설정 확인
    gmail_config = config_service.get_gmail_config(db)
    gmail_ok = bool(gmail_config["address"] and gmail_config["password"])
    if gmail_ok:
        email_service = get_email_service_with_config(
            gmail_config["address"], gmail_config["password"]
        )
    else:
        email_service = get_email_service()

    # 2. 수신자 확인
    daily_recipients = config_service.get_active_recipients(db, "daily")
    weekly_recipients = config_service.get_active_recipients(db, "weekly")

    # 3. 최근 보고서 상태
    recent_reports = (
        db.query(Report)
        .order_by(Report.generated_at.desc())
        .limit(5)
        .all()
    )

    # 4. 최근 Report-Agent 로그
    recent_logs = (
        db.query(AgentLog)
        .filter(AgentLog.agent_name == "Report-Agent")
        .order_by(AgentLog.executed_at.desc())
        .limit(5)
        .all()
    )

    # 5. 스케줄러 보고서 작업 상태
    report_jobs = []
    if scheduler.running:
        for job in scheduler.get_jobs():
            if "report" in job.id:
                report_jobs.append({
                    "id": job.id,
                    "name": job.name,
                    "next_run": str(job.next_run_time) if job.next_run_time else None,
                })

    # 6. 오늘 WorkItem 수
    today_start = now_kst().replace(hour=0, minute=0, second=0, microsecond=0)
    today_items = db.query(func.count(WorkItem.id)).filter(
        WorkItem.updated_at >= today_start
    ).scalar()

    issues = []
    if not gmail_ok and not email_service.is_configured:
        issues.append("Gmail 미설정 (GMAIL_ADDRESS, GMAIL_APP_PASSWORD)")
    if not daily_recipients:
        issues.append("일일보고 수신자 미설정")
    if not report_jobs:
        issues.append("스케줄러에 보고서 작업 미등록")
    if today_items == 0:
        issues.append("오늘 업데이트된 WorkItem 0건 (빈 보고서 발송 가능)")

    def _mask_email(email: str) -> str:
        """이메일 마스킹: user@domain.com → us***@domain.com"""
        if "@" not in email:
            return "***"
        local, domain = email.split("@", 1)
        return f"{local[:2]}***@{domain}" if len(local) > 2 else f"{local[0]}***@{domain}"

    return {
        "status": "ok" if not issues else "warning",
        "issues": issues,
        "gmail_configured": gmail_ok or email_service.is_configured,
        "gmail_address": gmail_config["address"][:3] + "***" if gmail_config["address"] else "",
        "recipients": {
            "daily": [_mask_email(e) for e in daily_recipients],
            "weekly": [_mask_email(e) for e in weekly_recipients],
            "daily_count": len(daily_recipients),
            "weekly_count": len(weekly_recipients),
        },
        "scheduler_report_jobs": report_jobs,
        "today_work_items": today_items,
        "recent_reports": [
            {
                "id": r.id,
                "type": r.report_type.value,
                "status": r.status.value,
                "subject": r.subject,
                "error": r.error_message,
                "generated_at": r.generated_at.isoformat() if r.generated_at else None,
                "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            }
            for r in recent_reports
        ],
        "recent_agent_logs": [
            {
                "action": log.action,
                "status": log.status,
                "detail": log.detail,
                "executed_at": log.executed_at.isoformat() if log.executed_at else None,
            }
            for log in recent_logs
        ],
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
    partial_sent_reports = db.query(func.count(Report.id)).filter(
        Report.status == ReportStatus.PARTIAL_SENT
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
            "partial_sent": partial_sent_reports,
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
