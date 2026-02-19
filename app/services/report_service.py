"""
보고서 생성 서비스
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..core.config import settings
from ..models.issue import WorkItem, ItemCategory
from ..models.report import Report, ReportItem, ReportType, ReportStatus

logger = logging.getLogger(__name__)

# Jinja2 템플릿 환경
_template_dir = settings.BASE_DIR / "app" / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_template_dir)),
    autoescape=select_autoescape(["html"]),
)


class ReportService:
    """보고서 생성/관리 서비스"""

    def generate_daily_report(self, db: Session) -> Report:
        """일일보고 생성"""
        now = datetime.now()
        period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        period_end = now

        return self._generate_report(
            db=db,
            report_type=ReportType.DAILY,
            period_start=period_start,
            period_end=period_end,
            subject=f"[일일업무보고] {now.strftime('%Y-%m-%d')}",
            template_name="daily_report.html",
        )

    def generate_weekly_report(self, db: Session) -> Report:
        """주간보고 생성"""
        now = datetime.now()
        period_start = now - timedelta(days=now.weekday())
        period_start = period_start.replace(hour=0, minute=0, second=0, microsecond=0)
        period_end = now

        week_str = now.strftime('%Y-%m-%d')
        return self._generate_report(
            db=db,
            report_type=ReportType.WEEKLY,
            period_start=period_start,
            period_end=period_end,
            subject=f"[주간업무보고] {period_start.strftime('%m/%d')}~{week_str}",
            template_name="weekly_report.html",
        )

    def generate_monthly_report(self, db: Session) -> Report:
        """월간보고 생성"""
        now = datetime.now()
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        period_end = now

        return self._generate_report(
            db=db,
            report_type=ReportType.MONTHLY,
            period_start=period_start,
            period_end=period_end,
            subject=f"[월간업무보고] {now.strftime('%Y년 %m월')}",
            template_name="monthly_report.html",
        )

    def _generate_report(
        self,
        db: Session,
        report_type: ReportType,
        period_start: datetime,
        period_end: datetime,
        subject: str,
        template_name: str,
    ) -> Report:
        """보고서 공통 생성 로직"""
        # 기간 내 업무 항목 조회
        items = (
            db.query(WorkItem)
            .filter(WorkItem.updated_at >= period_start)
            .filter(WorkItem.updated_at <= period_end)
            .order_by(WorkItem.category, WorkItem.updated_at.desc())
            .all()
        )

        # 분류별 그룹핑
        planned = [i for i in items if i.category == ItemCategory.PLANNED]
        required = [i for i in items if i.category == ItemCategory.REQUIRED]
        in_progress = [i for i in items if i.category == ItemCategory.IN_PROGRESS]

        # HTML 렌더링
        template = _jinja_env.get_template(template_name)
        html_content = template.render(
            report_type=report_type.value,
            period_start=period_start,
            period_end=period_end,
            planned_items=planned,
            required_items=required,
            in_progress_items=in_progress,
            generated_at=datetime.now(),
        )

        # Report 엔티티 생성
        report = Report(
            report_type=report_type,
            status=ReportStatus.GENERATED,
            period_start=period_start,
            period_end=period_end,
            subject=subject,
            recipients=settings.report_recipients,
            content_html=html_content,
        )

        # ReportItem 엔티티 생성
        for item in items:
            report_item = ReportItem(
                category=item.category.value,
                project_name=item.github_repo,
                title=item.title,
                detail=item.summary,
                source_type="issue" if item.github_issue_number else "commit",
                source_ref=item.github_issue_url or "",
            )
            report.items.append(report_item)

        db.add(report)
        db.commit()
        db.refresh(report)

        logger.info(f"보고서 생성 완료: {subject} (항목 {len(items)}건)")
        return report

    def get_report(self, db: Session, report_id: int) -> Report | None:
        """보고서 조회"""
        return db.query(Report).filter(Report.id == report_id).first()

    def get_reports(
        self,
        db: Session,
        report_type: ReportType = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Report]:
        """보고서 목록 조회"""
        query = db.query(Report).order_by(Report.generated_at.desc())
        if report_type:
            query = query.filter(Report.report_type == report_type)
        return query.offset(offset).limit(limit).all()


# 싱글톤
_service = None


def get_report_service() -> ReportService:
    global _service
    if _service is None:
        _service = ReportService()
    return _service
