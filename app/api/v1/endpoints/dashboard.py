"""
대시보드 HTML 페이지 엔드포인트
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ....core.config import settings, APP_VERSION
from ....core.database import get_db
from ....models.report import ReportType, ReportStatus
from ....models.issue import WorkItem, ItemCategory, ItemStatus
from ....services.report_service import get_report_service
from ....services.stats_service import get_stats_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# 대시보드 전용 Jinja2 환경
_template_dir = settings.BASE_DIR / "app" / "templates" / "dashboard"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_template_dir)),
    autoescape=select_autoescape(["html"]),
)


def _render(template_name: str, **kwargs) -> HTMLResponse:
    kwargs.setdefault("app_version", APP_VERSION)
    kwargs.setdefault("base_path", settings.root_path)
    template = _jinja_env.get_template(template_name)
    html = template.render(**kwargs)
    return HTMLResponse(content=html)


@router.get("", response_class=HTMLResponse)
def dashboard_home(db: Session = Depends(get_db)):
    """대시보드 메인 (최근 보고서 + 요약)"""
    service = get_report_service()
    stats_svc = get_stats_service()

    recent_reports = service.get_reports(db, limit=5)
    summary = stats_svc.get_summary(db, period_type="daily")

    return _render(
        "home.html",
        recent_reports=recent_reports,
        summary=summary,
        active_page="home",
    )


@router.get("/reports", response_class=HTMLResponse)
def report_list(
    report_type: str = Query(default=None),
    status: str = Query(default=None),
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
):
    """보고서 리스트 페이지"""
    service = get_report_service()
    limit = 20
    offset = (page - 1) * limit

    rt = None
    if report_type and report_type in ("daily", "weekly", "monthly"):
        rt = ReportType(report_type)

    reports = service.get_reports(db, report_type=rt, limit=limit, offset=offset)

    return _render(
        "report_list.html",
        reports=reports,
        current_type=report_type or "all",
        current_status=status or "all",
        current_page=page,
        active_page="reports",
    )


@router.get("/reports/table", response_class=HTMLResponse)
def report_table_partial(
    report_type: str = Query(default=None),
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
):
    """HTMX 파셜: 보고서 테이블"""
    service = get_report_service()
    limit = 20
    offset = (page - 1) * limit

    rt = None
    if report_type and report_type in ("daily", "weekly", "monthly"):
        rt = ReportType(report_type)

    reports = service.get_reports(db, report_type=rt, limit=limit, offset=offset)

    return _render(
        "partials/report_table.html",
        reports=reports,
        current_page=page,
        current_type=report_type or "all",
    )


@router.get("/reports/{report_id}", response_class=HTMLResponse)
def report_detail(report_id: int, db: Session = Depends(get_db)):
    """보고서 상세 페이지"""
    service = get_report_service()
    report = service.get_report(db, report_id)
    if not report:
        return HTMLResponse(content="<h1>404 - 보고서를 찾을 수 없습니다</h1>", status_code=404)

    return _render(
        "report_detail.html",
        report=report,
        active_page="reports",
    )


@router.get("/work-items", response_class=HTMLResponse)
def work_items_page(
    category: str = Query(default=None),
    status: str = Query(default=None),
    repo: str = Query(default=None),
    q: str = Query(default=None),
    group_by: str = Query(default=None),
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
):
    """업무 항목 목록 페이지"""
    limit = 50
    offset = (page - 1) * limit

    query = db.query(WorkItem).order_by(WorkItem.updated_at.desc())

    if category and category in ("planned", "required", "in_progress"):
        query = query.filter(WorkItem.category == ItemCategory(category))
    if status and status in ("open", "in_progress", "resolved", "closed"):
        query = query.filter(WorkItem.status == ItemStatus(status))
    if repo:
        query = query.filter(WorkItem.github_repo == repo)
    if q:
        query = query.filter(WorkItem.title.ilike(f"%{q}%"))

    total_count = query.count()
    items = query.offset(offset).limit(limit).all()

    # 프로젝트 목록 (필터 드롭다운용)
    repos = [r[0] for r in db.query(WorkItem.github_repo).distinct().order_by(WorkItem.github_repo).all()]

    # 프로젝트별 그룹 뷰
    project_groups = None
    if group_by == "project":
        from collections import defaultdict
        groups = defaultdict(list)
        all_items = query.limit(500).all()
        for item in all_items:
            groups[item.github_repo].append(item)
        project_groups = dict(sorted(groups.items(), key=lambda x: len(x[1]), reverse=True))

    return _render(
        "work_items.html",
        items=items,
        repos=repos,
        current_category=category or "all",
        current_status=status or "all",
        current_repo=repo or "all",
        current_q=q or "",
        current_page=page,
        total_count=total_count,
        group_by=group_by,
        project_groups=project_groups,
        active_page="work_items",
    )


@router.get("/work-items/table", response_class=HTMLResponse)
def work_items_table_partial(
    category: str = Query(default=None),
    status: str = Query(default=None),
    repo: str = Query(default=None),
    q: str = Query(default=None),
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
):
    """HTMX 파셜: 업무 항목 테이블"""
    limit = 50
    offset = (page - 1) * limit

    query = db.query(WorkItem).order_by(WorkItem.updated_at.desc())

    if category and category in ("planned", "required", "in_progress"):
        query = query.filter(WorkItem.category == ItemCategory(category))
    if status and status in ("open", "in_progress", "resolved", "closed"):
        query = query.filter(WorkItem.status == ItemStatus(status))
    if repo:
        query = query.filter(WorkItem.github_repo == repo)
    if q:
        query = query.filter(WorkItem.title.ilike(f"%{q}%"))

    total_count = query.count()
    items = query.offset(offset).limit(limit).all()

    return _render(
        "partials/work_items_table.html",
        items=items,
        current_category=category or "all",
        current_status=status or "all",
        current_repo=repo or "all",
        current_q=q or "",
        current_page=page,
        total_count=total_count,
    )


@router.get("/stats", response_class=HTMLResponse)
def stats_page(
    period_type: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    db: Session = Depends(get_db),
):
    """통계 페이지"""
    stats_svc = get_stats_service()
    summary = stats_svc.get_summary(db, period_type=period_type)
    trend = stats_svc.get_trend(db, period_type=period_type)
    report_stats = stats_svc.get_report_stats(db)

    return _render(
        "stats.html",
        summary=summary,
        trend=trend,
        report_stats=report_stats,
        current_period=period_type,
        active_page="stats",
    )
