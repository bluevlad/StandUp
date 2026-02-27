"""
Report-Agent
보고서 생성 및 이메일 발송 관리
"""

import time
import logging
from datetime import datetime

from ..core.database import SessionLocal
from ..services.report_service import get_report_service
from ..services.email_service import get_email_service, get_email_service_with_config
from ..services import config_service
from ..models.report import Report, ReportStatus
from ..models.agent_log import AgentLog

logger = logging.getLogger(__name__)


class ReportAgent:
    """보고서 생성/발송 Agent"""

    def send_daily_report(self):
        """일일보고 생성 및 발송"""
        self._run_report("daily", "일일업무보고")

    def send_weekly_report(self):
        """주간보고 생성 및 발송"""
        self._run_report("weekly", "주간업무보고")

    def send_monthly_report(self):
        """월간보고 생성 및 발송"""
        self._run_report("monthly", "월간업무보고")

    def _run_report(self, report_type: str, report_label: str):
        """보고서 생성/발송 공통 로직 (AgentLog 기록 포함)"""
        logger.info(f"=== {report_label} 생성 시작 ===")
        start_time = time.time()

        db = SessionLocal()
        try:
            report_service = get_report_service()

            if report_type == "daily":
                report = report_service.generate_daily_report(db)
            elif report_type == "weekly":
                report = report_service.generate_weekly_report(db)
            else:
                report = report_service.generate_monthly_report(db)

            self._send_report(db, report)

            duration = time.time() - start_time
            status_str = report.status.value
            detail = f"{report.subject} → {status_str}"
            if report.error_message:
                detail += f" ({report.error_message})"

            log = AgentLog(
                agent_name="Report-Agent",
                action=f"{report_type}_report",
                status="success" if report.status == ReportStatus.SENT else "error",
                detail=detail,
                items_processed=len(report.items),
                duration_seconds=round(duration, 2),
            )
            db.add(log)
            db.commit()
            logger.info(f"=== {report_label} 완료: {status_str} ({duration:.1f}초) ===")

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"{report_label} 오류: {e}", exc_info=True)
            try:
                log = AgentLog(
                    agent_name="Report-Agent",
                    action=f"{report_type}_report",
                    status="error",
                    detail=str(e)[:1000],
                    duration_seconds=round(duration, 2),
                )
                db.add(log)
                db.commit()
            except Exception:
                pass
        finally:
            db.close()

    def _send_report(self, db, report: Report):
        """보고서 이메일 발송"""
        # DB에서 수신자 조회 (DB → .env fallback)
        report_type = report.report_type.value.lower()
        recipients = config_service.get_active_recipients(db, report_type)

        if not recipients:
            logger.warning("이메일 수신자가 설정되지 않았습니다.")
            report.status = ReportStatus.FAILED
            report.error_message = "수신자 미설정"
            db.commit()
            return

        # DB에서 Gmail 설정 조회 (DB → .env fallback)
        gmail_config = config_service.get_gmail_config(db)
        if gmail_config["address"] and gmail_config["password"]:
            email_service = get_email_service_with_config(
                gmail_config["address"], gmail_config["password"]
            )
        else:
            email_service = get_email_service()

        if not email_service.is_configured:
            logger.warning("이메일 서비스가 설정되지 않았습니다.")
            report.status = ReportStatus.FAILED
            report.error_message = "Gmail 미설정"
            db.commit()
            return

        logger.info(f"이메일 발송 시작: 수신자 {len(recipients)}명 → {recipients}")

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
