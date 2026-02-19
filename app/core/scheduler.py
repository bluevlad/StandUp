"""
APScheduler 스케줄러 설정
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import settings

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="Asia/Seoul")


def setup_scheduler():
    """스케줄러 초기화 및 작업 등록"""
    from ..agents.qa_agent import get_qa_agent
    from ..agents.tobe_agent import get_tobe_agent
    from ..agents.report_agent import get_report_agent

    qa_agent = get_qa_agent()
    tobe_agent = get_tobe_agent()
    report_agent = get_report_agent()

    # QA-Agent: 매 2시간 실행 (업무시간 내)
    scheduler.add_job(
        qa_agent.run,
        CronTrigger(hour="8-18/2", minute=0, day_of_week="mon-fri"),
        id="qa_agent_scan",
        name="QA-Agent Issues 스캔",
        replace_existing=True,
    )

    # Tobe-Agent: 매 1시간 실행 (업무시간 내)
    scheduler.add_job(
        tobe_agent.run,
        CronTrigger(hour="8-18", minute=30, day_of_week="mon-fri"),
        id="tobe_agent_track",
        name="Tobe-Agent 진행사항 추적",
        replace_existing=True,
    )

    # 일일보고: 월~금 16:30 생성 → 17:00까지 발송
    scheduler.add_job(
        report_agent.send_daily_report,
        CronTrigger(
            hour=settings.daily_report_hour,
            minute=settings.daily_report_minute,
            day_of_week="mon-fri",
        ),
        id="daily_report",
        name="일일업무보고 발송",
        replace_existing=True,
    )

    # 주간보고: 금요일 09:30 생성 → 10:00까지 발송
    scheduler.add_job(
        report_agent.send_weekly_report,
        CronTrigger(
            hour=settings.weekly_report_hour,
            minute=settings.weekly_report_minute,
            day_of_week="fri",
        ),
        id="weekly_report",
        name="주간업무보고 발송",
        replace_existing=True,
    )

    # 월간보고: 마지막주 금요일 10:30 생성 → 11:00까지 발송
    # APScheduler에서 "마지막주 금요일"은 day="last fri"로 처리
    scheduler.add_job(
        report_agent.send_monthly_report,
        CronTrigger(
            hour=settings.monthly_report_hour,
            minute=settings.monthly_report_minute,
            day="last fri",
        ),
        id="monthly_report",
        name="월간업무보고 발송",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("스케줄러 시작 완료")

    # 등록된 작업 목록 출력
    jobs = scheduler.get_jobs()
    for job in jobs:
        logger.info(f"  등록된 작업: {job.name} (다음 실행: {job.next_run_time})")


def shutdown_scheduler():
    """스케줄러 종료"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("스케줄러 종료 완료")
