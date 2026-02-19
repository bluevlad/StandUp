"""
보고서 생성 서비스
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..core.config import settings
from ..models.issue import WorkItem, ItemCategory, ItemStatus
from ..models.report import Report, ReportItem, ReportType, ReportStatus
from ..services import config_service

logger = logging.getLogger(__name__)

# Jinja2 템플릿 환경
_template_dir = settings.BASE_DIR / "app" / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_template_dir)),
    autoescape=select_autoescape(["html"]),
)


def _group_by_project(items, max_projects, max_items):
    """항목을 프로젝트별로 그룹핑하고 상위 N건만 추출"""
    by_repo = defaultdict(list)
    for item in items:
        by_repo[item.github_repo].append(item)

    # 건수 내림차순 정렬
    sorted_repos = sorted(by_repo.items(), key=lambda x: len(x[1]), reverse=True)

    visible_groups = []
    for repo, repo_items in sorted_repos[:max_projects]:
        visible_groups.append({
            "repo": repo,
            "total_count": len(repo_items),
            "top_items": repo_items[:max_items],
            "remaining_count": max(0, len(repo_items) - max_items),
        })

    hidden_repos = sorted_repos[max_projects:]
    hidden_projects_count = len(hidden_repos)
    hidden_items_count = sum(len(repo_items) for _, repo_items in hidden_repos)

    return {
        "groups": visible_groups,
        "total_count": len(items),
        "hidden_projects_count": hidden_projects_count,
        "hidden_items_count": hidden_items_count,
        "project_count": len(sorted_repos),
    }


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
        # DB-first, .env fallback
        max_projects = config_service.get_setting_int(db, "max_projects_per_category", settings.max_projects_per_category)
        max_items = config_service.get_setting_int(db, "max_items_per_project", settings.max_items_per_project)

        # 수신자 조회 (DB → .env fallback)
        recipients = config_service.get_active_recipients(db, report_type.value.lower())
        recipients_str = ",".join(recipients)

        # 기간 내 업무 항목 조회
        items = (
            db.query(WorkItem)
            .filter(WorkItem.updated_at >= period_start)
            .filter(WorkItem.updated_at <= period_end)
            .order_by(WorkItem.category, WorkItem.updated_at.desc())
            .all()
        )

        # 분류별 분리
        planned = [i for i in items if i.category == ItemCategory.PLANNED]
        required = [i for i in items if i.category == ItemCategory.REQUIRED]
        in_progress = [i for i in items if i.category == ItemCategory.IN_PROGRESS]

        # 프로젝트별 그룹핑
        planned_grouped = _group_by_project(planned, max_projects, max_items)
        required_grouped = _group_by_project(required, max_projects, max_items)
        progress_grouped = _group_by_project(in_progress, max_projects, max_items)

        # 완료 건수
        resolved_count = sum(
            1 for i in items
            if i.status in (ItemStatus.RESOLVED, ItemStatus.CLOSED)
        )

        # 전체 프로젝트 수
        all_repos = set(i.github_repo for i in items)

        # HTML 렌더링
        template = _jinja_env.get_template(template_name)
        html_content = template.render(
            report_type=report_type.value,
            period_start=period_start,
            period_end=period_end,
            total_count=len(items),
            project_count=len(all_repos),
            resolved_count=resolved_count,
            planned=planned_grouped,
            required=required_grouped,
            in_progress=progress_grouped,
            generated_at=datetime.now(),
        )

        # Report 엔티티 생성
        report = Report(
            report_type=report_type,
            status=ReportStatus.GENERATED,
            period_start=period_start,
            period_end=period_end,
            subject=subject,
            recipients=recipients_str,
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
