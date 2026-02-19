"""
PostgreSQL 환경 전체 통합 검증
Usage: python -m scripts.test_full_integration
"""

import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    from app.core.database import SessionLocal
    from app.core.config import settings
    from app.models.issue import WorkItem, ItemCategory
    from app.models.report import Report, ReportStatus
    from app.models.agent_log import AgentLog
    from app.agents.qa_agent import QAAgent
    from app.agents.tobe_agent import TobeAgent
    from app.services.report_service import ReportService
    from app.services.email_service import EmailService
    from sqlalchemy import func

    logger.info("=== PostgreSQL 전체 통합 검증 ===")
    logger.info(f"DB: {settings.database_url}")

    db = SessionLocal()
    try:
        # DB 연결 확인
        count = db.query(func.count(WorkItem.id)).scalar()
        logger.info(f"현재 DB work_items: {count}건")

        # Step 1: QA-Agent
        logger.info("\n[ Step 1 ] QA-Agent 실행")
        qa = QAAgent()
        qa.run()

        qa_count = db.query(func.count(WorkItem.id)).scalar()
        logger.info(f"  QA-Agent 후 work_items: {qa_count}건")

        # Step 2: Tobe-Agent
        logger.info("\n[ Step 2 ] Tobe-Agent 실행")
        tobe = TobeAgent()
        tobe.run()

        tobe_count = db.query(func.count(WorkItem.id)).scalar()
        logger.info(f"  Tobe-Agent 후 work_items: {tobe_count}건")

        # Step 3: 보고서 생성
        logger.info("\n[ Step 3 ] 일일보고서 생성")
        report_service = ReportService()
        report = report_service.generate_daily_report(db)
        logger.info(f"  보고서: {report.subject} (항목 {len(report.items)}건)")

        # Step 4: 이메일 발송
        logger.info("\n[ Step 4 ] 이메일 발송")
        email_service = EmailService()
        if email_service.is_configured:
            result = email_service.send(
                recipient=settings.gmail_address,
                subject=report.subject,
                html_content=report.content_html,
            )
            if result.success:
                from datetime import datetime
                report.status = ReportStatus.SENT
                report.sent_at = datetime.now()
                db.commit()
                logger.info(f"  발송 성공! -> {settings.gmail_address}")
            else:
                logger.error(f"  발송 실패: {result.error_message}")

        # Step 5: Agent 이력 확인
        logger.info("\n[ Step 5 ] Agent 실행 이력 확인")
        logs = db.query(AgentLog).order_by(AgentLog.executed_at.desc()).limit(5).all()
        for log in logs:
            logger.info(
                f"  [{log.agent_name}] {log.status} - {log.detail} "
                f"({log.duration_seconds}초)"
            )

        # 최종 통계
        logger.info("\n=== 최종 통계 ===")
        planned = db.query(func.count(WorkItem.id)).filter(
            WorkItem.category == ItemCategory.PLANNED
        ).scalar()
        required = db.query(func.count(WorkItem.id)).filter(
            WorkItem.category == ItemCategory.REQUIRED
        ).scalar()
        in_progress = db.query(func.count(WorkItem.id)).filter(
            WorkItem.category == ItemCategory.IN_PROGRESS
        ).scalar()
        total_reports = db.query(func.count(Report.id)).scalar()
        sent_reports = db.query(func.count(Report.id)).filter(
            Report.status == ReportStatus.SENT
        ).scalar()
        total_logs = db.query(func.count(AgentLog.id)).scalar()

        logger.info(f"  업무항목: {planned + required + in_progress}건")
        logger.info(f"    - 예정사항: {planned}건")
        logger.info(f"    - 요구사항: {required}건")
        logger.info(f"    - 진행사항: {in_progress}건")
        logger.info(f"  보고서: {total_reports}건 (발송: {sent_reports}건)")
        logger.info(f"  Agent 이력: {total_logs}건")
        logger.info("\n=== 통합 검증 완료 ===")

    finally:
        db.close()


if __name__ == "__main__":
    main()
