"""
전체 파이프라인 통합 테스트
Agent scan -> Report generate -> Email send
Usage: python -m scripts.test_pipeline
"""

import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_URL"] = "sqlite:///./test_pipeline.db"

from dotenv import load_dotenv
load_dotenv(override=False)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    from app.core.database import engine, Base, SessionLocal
    from app.core.config import settings
    from app.models import WorkItem, Report, ReportItem  # noqa: F401
    from app.models.issue import ItemCategory
    from app.models.report import ReportType, ReportStatus
    from app.agents.qa_agent import QAAgent
    from app.agents.tobe_agent import TobeAgent
    from app.services.report_service import ReportService
    from app.services.email_service import EmailService

    # DB setup
    Base.metadata.create_all(bind=engine)
    logger.info("=== 전체 파이프라인 통합 테스트 ===\n")

    # Step 1: QA-Agent
    logger.info("[ Step 1 ] QA-Agent 실행")
    qa = QAAgent()
    qa.run()

    # Step 2: Tobe-Agent
    logger.info("\n[ Step 2 ] Tobe-Agent 실행")
    tobe = TobeAgent()
    tobe.run()

    # Step 3: Report 생성
    logger.info("\n[ Step 3 ] 일일보고서 생성")
    db = SessionLocal()
    try:
        report_service = ReportService()
        report = report_service.generate_daily_report(db)
        logger.info(f"  보고서 ID: {report.id}")
        logger.info(f"  제목: {report.subject}")
        logger.info(f"  항목 수: {len(report.items)}건")
        logger.info(f"  상태: {report.status.value}")

        # 항목 요약
        categories = {}
        for item in report.items:
            categories[item.category] = categories.get(item.category, 0) + 1
        for cat, count in categories.items():
            logger.info(f"    {cat}: {count}건")

        # Step 4: Email 발송
        logger.info(f"\n[ Step 4 ] 이메일 발송 테스트")
        email_service = EmailService()

        if not email_service.is_configured:
            logger.warning("Gmail 미설정. 발송 건너뜀.")
        else:
            recipient = settings.gmail_address
            result = email_service.send(
                recipient=recipient,
                subject=report.subject,
                html_content=report.content_html,
            )

            if result.success:
                from datetime import datetime
                report.status = ReportStatus.SENT
                report.sent_at = datetime.now()
                db.commit()
                logger.info(f"  발송 성공! -> {recipient}")
            else:
                logger.error(f"  발송 실패: {result.error_message}")

        # 최종 결과
        logger.info(f"\n=== 통합 테스트 결과 ===")
        total_items = db.query(WorkItem).count()
        total_reports = db.query(Report).count()
        sent_reports = db.query(Report).filter(Report.status == ReportStatus.SENT).count()
        logger.info(f"  업무 항목: {total_items}건")
        logger.info(f"  보고서: {total_reports}건 (발송완료: {sent_reports}건)")
        logger.info(f"=== 통합 테스트 완료 ===")

    finally:
        db.close()

    # cleanup
    engine.dispose()
    try:
        if os.path.exists("./test_pipeline.db"):
            os.remove("./test_pipeline.db")
    except PermissionError:
        pass


if __name__ == "__main__":
    main()
