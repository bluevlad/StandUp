"""
Report-Agent
보고서 생성 및 이메일 발송 관리
"""

import logging
from datetime import datetime

from ..core.config import settings
from ..core.database import SessionLocal
from ..services.report_service import get_report_service
from ..services.email_service import get_email_service
from ..models.report import Report, ReportStatus

logger = logging.getLogger(__name__)


class ReportAgent:
    """보고서 생성/발송 Agent"""

    def send_daily_report(self):
        """일일보고 생성 및 발송"""
        logger.info("=== 일일업무보고 생성 시작 ===")
        db = SessionLocal()
        try:
            report_service = get_report_service()
            report = report_service.generate_daily_report(db)
            self._send_report(db, report)
        except Exception as e:
            logger.error(f"일일보고 오류: {e}", exc_info=True)
        finally:
            db.close()

    def send_weekly_report(self):
        """주간보고 생성 및 발송"""
        logger.info("=== 주간업무보고 생성 시작 ===")
        db = SessionLocal()
        try:
            report_service = get_report_service()
            report = report_service.generate_weekly_report(db)
            self._send_report(db, report)
        except Exception as e:
            logger.error(f"주간보고 오류: {e}", exc_info=True)
        finally:
            db.close()

    def send_monthly_report(self):
        """월간보고 생성 및 발송"""
        logger.info("=== 월간업무보고 생성 시작 ===")
        db = SessionLocal()
        try:
            report_service = get_report_service()
            report = report_service.generate_monthly_report(db)
            self._send_report(db, report)
        except Exception as e:
            logger.error(f"월간보고 오류: {e}", exc_info=True)
        finally:
            db.close()

    def _send_report(self, db, report: Report):
        """보고서 이메일 발송"""
        email_service = get_email_service()
        recipients = settings.recipient_list

        if not recipients:
            logger.warning("이메일 수신자가 설정되지 않았습니다.")
            report.status = ReportStatus.FAILED
            report.error_message = "수신자 미설정"
            db.commit()
            return

        if not email_service.is_configured:
            logger.warning("이메일 서비스가 설정되지 않았습니다.")
            report.status = ReportStatus.FAILED
            report.error_message = "Gmail 미설정"
            db.commit()
            return

        results = email_service.send_batch(
            recipients=recipients,
            subject=report.subject,
            html_content=report.content_html,
        )

        success_count = sum(1 for r in results if r.success)
        if success_count == len(recipients):
            report.status = ReportStatus.SENT
            report.sent_at = datetime.now()
            logger.info(f"보고서 발송 완료: {report.subject}")
        elif success_count > 0:
            report.status = ReportStatus.SENT
            report.sent_at = datetime.now()
            failed = [r for r in results if not r.success]
            report.error_message = f"일부 실패: {[r.recipient for r in failed]}"
            logger.warning(f"보고서 부분 발송: {success_count}/{len(recipients)}")
        else:
            report.status = ReportStatus.FAILED
            report.retry_count += 1
            report.error_message = results[0].error_message if results else "알 수 없는 오류"
            logger.error(f"보고서 발송 실패: {report.subject}")

        db.commit()


# 싱글톤
_agent = None


def get_report_agent() -> ReportAgent:
    global _agent
    if _agent is None:
        _agent = ReportAgent()
    return _agent
