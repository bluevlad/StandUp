"""
APScheduler 스케줄러 설정
"""

import logging
import threading
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from .config import settings

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(
    timezone="Asia/Seoul",
    job_defaults={
        "coalesce": True,
        "max_instances": 1,
        "misfire_grace_time": 300,
    },
)


def _job_listener(event):
    """스케줄러 작업 실행 이벤트 리스너"""
    job_id = event.job_id
    if event.exception:
        logger.error(f"스케줄 작업 실패: {job_id} - {event.exception}")
    else:
        logger.info(f"스케줄 작업 완료: {job_id}")


def run_initial_scan():
    """앱 시작 시 초기 스캔 (별도 스레드)"""
    from ..agents.qa_agent import get_qa_agent
    from ..agents.tobe_agent import get_tobe_agent

    logger.info("=== 초기 Agent 스캔 시작 ===")
    try:
        qa_agent = get_qa_agent()
        qa_agent.run()

        tobe_agent = get_tobe_agent()
        tobe_agent.run()

        logger.info("=== 초기 Agent 스캔 완료 ===")
    except Exception as e:
        logger.error(f"초기 스캔 오류: {e}", exc_info=True)


def _safe_add_job(func, trigger, job_id, job_name):
    """안전한 작업 등록 (개별 실패가 다른 작업에 영향 없도록)"""
    try:
        scheduler.add_job(
            func, trigger,
            id=job_id, name=job_name,
            replace_existing=True,
        )
        logger.info(f"  스케줄 작업 등록: {job_name}")
    except Exception as e:
        logger.error(f"  스케줄 작업 등록 실패: {job_name} - {e}", exc_info=True)


def setup_scheduler():
    """스케줄러 초기화 및 작업 등록"""
    from ..agents.qa_agent import get_qa_agent
    from ..agents.tobe_agent import get_tobe_agent
    from ..agents.report_agent import get_report_agent

    qa_agent = get_qa_agent()
    tobe_agent = get_tobe_agent()
    report_agent = get_report_agent()

    # 이벤트 리스너 등록
    scheduler.add_listener(_job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    # QA-Agent: 매 2시간 실행 (업무시간 내)
    _safe_add_job(
        qa_agent.run,
        CronTrigger(hour="8-18/2", minute=0, day_of_week="mon-fri"),
        "qa_agent_scan", "QA-Agent Issues 스캔",
    )

    # Tobe-Agent: 매 1시간 실행 (업무시간 내)
    _safe_add_job(
        tobe_agent.run,
        CronTrigger(hour="8-18", minute=30, day_of_week="mon-fri"),
        "tobe_agent_track", "Tobe-Agent 진행사항 추적",
    )

    # 일일보고: 월~금
    _safe_add_job(
        report_agent.send_daily_report,
        CronTrigger(
            hour=settings.daily_report_hour,
            minute=settings.daily_report_minute,
            day_of_week="mon-fri",
        ),
        "daily_report", "일일업무보고 발송",
    )

    # 주간보고: 금요일
    _safe_add_job(
        report_agent.send_weekly_report,
        CronTrigger(
            hour=settings.weekly_report_hour,
            minute=settings.weekly_report_minute,
            day_of_week="fri",
        ),
        "weekly_report", "주간업무보고 발송",
    )

    # 월간보고: 마지막주 금요일
    _safe_add_job(
        report_agent.send_monthly_report,
        CronTrigger(
            hour=settings.monthly_report_hour,
            minute=settings.monthly_report_minute,
            day="last fri",
        ),
        "monthly_report", "월간업무보고 발송",
    )

    scheduler.start()
    logger.info("스케줄러 시작 완료")

    # 등록된 작업 목록 출력
    jobs = scheduler.get_jobs()
    for job in jobs:
        logger.info(f"  등록된 작업: {job.name} (다음 실행: {job.next_run_time})")

    # 초기 스캔을 별도 스레드에서 실행 (앱 시작 블로킹 방지)
    init_thread = threading.Thread(target=run_initial_scan, daemon=True)
    init_thread.start()
    logger.info("초기 Agent 스캔을 백그라운드에서 시작합니다.")


def get_scheduler_status() -> dict:
    """스케줄러 상태 조회 (진단용)"""
    status = {
        "running": scheduler.running,
        "jobs": [],
    }
    if scheduler.running:
        for job in scheduler.get_jobs():
            status["jobs"].append({
                "id": job.id,
                "name": job.name,
                "next_run_time": str(job.next_run_time) if job.next_run_time else None,
                "pending": job.pending,
            })
    return status


def shutdown_scheduler():
    """스케줄러 종료"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("스케줄러 종료 완료")
