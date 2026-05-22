"""
APScheduler 스케줄러 설정
"""

import logging
import threading
from datetime import date

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
    logger.info("=== 초기 Agent 스캔 시작 ===")
    try:
        if settings.is_legacy_mode:
            from ..agents.qa_agent import get_qa_agent
            from ..agents.tobe_agent import get_tobe_agent

            qa_agent = get_qa_agent()
            qa_agent.run()

            tobe_agent = get_tobe_agent()
            tobe_agent.run()

        if settings.is_insight_mode:
            # 초기 ingestion 만 실행 — 합성/발송은 스케줄에 맡김
            from ..ingestion.hub import IngestionHub
            try:
                result = IngestionHub(embed_chunks=True).run()
                logger.info("초기 ingestion: new_events=%d new_chunks=%d",
                            result.new_events, result.new_chunks)
            except Exception as e:  # noqa: BLE001
                logger.warning("초기 ingestion 실패 (스케줄 동작은 무관): %s", e)

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
    """스케줄러 초기화 및 작업 등록.

    STANDUP_MODE:
    - legacy : QA/Tobe agent 데이터 수집 (일/주/월 보고 발송은 제거됨)
    - insight: 신규 주간 인사이트 뉴스레터 (cascade + RAG)
    - both   : 둘 다 실행 (전환기 병행 운영)
    """
    # 이벤트 리스너 등록
    scheduler.add_listener(_job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    # 스케줄러 timezone (CronTrigger에 명시적 전달 필수 - 컨테이너 UTC 대응)
    tz = "Asia/Seoul"

    logger.info("스케줄러 모드: %s", settings.standup_mode)

    if settings.is_legacy_mode:
        from ..agents.qa_agent import get_qa_agent
        from ..agents.tobe_agent import get_tobe_agent

        qa_agent = get_qa_agent()
        tobe_agent = get_tobe_agent()

        # QA-Agent: 매 2시간 실행 (업무시간 내)
        _safe_add_job(
            qa_agent.run,
            CronTrigger(hour="8-18/2", minute=0, day_of_week="mon-fri", timezone=tz),
            "qa_agent_scan", "QA-Agent Issues 스캔",
        )

        # Tobe-Agent: 매 1시간 실행 (업무시간 내)
        _safe_add_job(
            tobe_agent.run,
            CronTrigger(hour="8-18", minute=30, day_of_week="mon-fri", timezone=tz),
            "tobe_agent_track", "Tobe-Agent 진행사항 추적",
        )

    if settings.is_insight_mode:
        from ..agents_v2.insight_newsletter import run_weekly_job

        _safe_add_job(
            run_weekly_job,
            CronTrigger(
                day_of_week=settings.insight_weekly_dow,
                hour=settings.insight_weekly_hour,
                minute=settings.insight_weekly_minute,
                timezone=tz,
            ),
            "insight_weekly", "Insight 주간 뉴스레터 발송 (exaone3.5 cascade)",
        )

        # HopenTechBrief — 일일 (PR6). insight 모드 안에서 별도 토글로 제어.
        if settings.hopen_brief_daily_enabled:
            from ..agents_v2.hopen_tech_brief import run_daily_job

            _safe_add_job(
                run_daily_job,
                CronTrigger(
                    hour=settings.hopen_brief_daily_hour,
                    minute=settings.hopen_brief_daily_minute,
                    timezone=tz,
                ),
                "hopen_tech_brief_daily",
                "HopenTechBrief 일일 카드 메일 발송 (게이트+detailer)",
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
