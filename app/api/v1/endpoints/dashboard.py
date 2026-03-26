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
from ....services.dev_plan_service import get_dev_plan_service
from ....models.dev_plan import DevPlan, PlanStatus, PlanItemStatus

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
    if status == "completed":
        query = query.filter(WorkItem.status.in_([ItemStatus.RESOLVED, ItemStatus.CLOSED]))
    elif status and status in ("open", "in_progress", "resolved", "closed"):
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
    if status == "completed":
        query = query.filter(WorkItem.status.in_([ItemStatus.RESOLVED, ItemStatus.CLOSED]))
    elif status and status in ("open", "in_progress", "resolved", "closed"):
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


@router.get("/dev-plans", response_class=HTMLResponse)
def dev_plans_page(db: Session = Depends(get_db)):
    """개발 플랜 현황 페이지"""
    service = get_dev_plan_service()
    overall = service.get_overall_metrics(db)
    projects = service.get_project_summary(db)

    # 프로젝트별 플랜 목록 (상세 링크용)
    from sqlalchemy.orm import joinedload
    all_plans = (
        db.query(DevPlan)
        .filter(DevPlan.status.in_([PlanStatus.ACTIVE, PlanStatus.COMPLETED]))
        .order_by(DevPlan.project_name, DevPlan.updated_at.desc())
        .all()
    )
    plans_by_project: dict[str, list] = {}
    for plan in all_plans:
        plans_by_project.setdefault(plan.project_name, []).append(plan)

    return _render(
        "dev_plans.html",
        overall=overall,
        projects=projects,
        plans_by_project=plans_by_project,
        active_page="dev_plans",
    )


@router.get("/dev-plans/{plan_id}", response_class=HTMLResponse)
def dev_plan_detail(plan_id: int, db: Session = Depends(get_db)):
    """개발 플랜 상세 페이지"""
    service = get_dev_plan_service()
    plan = service.get_plan(db, plan_id)
    if not plan:
        return HTMLResponse(content="<h1>404 - 플랜을 찾을 수 없습니다</h1>", status_code=404)

    # Phase별 그룹핑
    from collections import OrderedDict
    phases: dict[int, list] = OrderedDict()
    for item in plan.items:
        phases.setdefault(item.phase, []).append(item)

    done_count = sum(1 for item in plan.items if item.status == PlanItemStatus.DONE)

    return _render(
        "dev_plan_detail.html",
        plan=plan,
        phases=phases,
        done_count=done_count,
        active_page="dev_plans",
    )


@router.get("/projects", response_class=HTMLResponse)
def projects_overview(db: Session = Depends(get_db)):
    """프로젝트 Overview 페이지"""
    stats_svc = get_stats_service()
    dev_plan_svc = get_dev_plan_service()

    work_stats = stats_svc.get_all_projects_overview(db)
    plan_summary = dev_plan_svc.get_project_summary(db)
    overall = dev_plan_svc.get_overall_metrics(db)

    # work_stats + plan_summary 병합
    plan_map = {p["project_name"]: p for p in plan_summary}
    projects = []
    for ws in work_stats:
        ps = plan_map.get(ws["project_name"], {})
        projects.append({
            **ws,
            "progress_pct": ps.get("progress_pct", 0.0),
            "completion_pct": ps.get("completion_pct", 0.0),
            "quality_score": ps.get("quality_score", 0.0),
            "plan_count": ps.get("plan_count", 0),
            "plan_total_items": ps.get("total_items", 0),
            "plan_done_items": ps.get("done_items", 0),
            "active_plan_title": ps.get("active_plan_title"),
            "current_phase": 0,
            "total_phases": 0,
        })
        # 활성 플랜의 phase 정보 추가
        if ps.get("plan_count", 0) > 0:
            active_plan = (
                db.query(DevPlan)
                .filter(DevPlan.project_name == ws["project_name"], DevPlan.status == PlanStatus.ACTIVE)
                .first()
            )
            if active_plan:
                projects[-1]["current_phase"] = active_plan.current_phase
                projects[-1]["total_phases"] = active_plan.total_phases

    # 전체 Work Items 종합
    total_work_items = sum(p["total_items"] for p in projects)
    total_resolved = sum(p["resolved_count"] for p in projects)
    total_in_progress = sum(p["in_progress_count"] for p in projects)
    total_open = sum(p["open_count"] for p in projects)
    overall_completion = round((total_resolved / total_work_items * 100), 1) if total_work_items > 0 else 0.0

    return _render(
        "project_overview.html",
        projects=projects,
        overall=overall,
        total_work_items=total_work_items,
        total_resolved=total_resolved,
        total_in_progress=total_in_progress,
        total_open=total_open,
        overall_completion=overall_completion,
        active_page="projects",
    )


@router.get("/projects/{project_name}", response_class=HTMLResponse)
def project_detail(
    project_name: str,
    period_type: str = Query(default="weekly", pattern="^(daily|weekly|monthly)$"),
    db: Session = Depends(get_db),
):
    """프로젝트 상세 통계 페이지"""
    stats_svc = get_stats_service()
    dev_plan_svc = get_dev_plan_service()

    # TARGET_PROJECTS에서 repo 찾기
    from ....services.dev_plan_service import TARGET_PROJECTS
    proj_info = next((p for p in TARGET_PROJECTS if p["name"] == project_name), None)
    if not proj_info:
        return HTMLResponse(content="<h1>404 - 프로젝트를 찾을 수 없습니다</h1>", status_code=404)

    github_repo = proj_info["repo"]

    # Work Items 통계
    work_stats = stats_svc.get_project_work_stats(db, github_repo)

    # Work Items 추이
    trend = stats_svc.get_project_trend(db, github_repo, period_type)

    # Dev Plan 정보
    plan_projects = dev_plan_svc.get_project_summary(db)
    plan_info = next((p for p in plan_projects if p["project_name"] == project_name), {})

    # 해당 프로젝트의 플랜 목록
    from sqlalchemy.orm import joinedload
    plans = (
        db.query(DevPlan)
        .options(joinedload(DevPlan.items))
        .filter(DevPlan.project_name == project_name)
        .order_by(DevPlan.updated_at.desc())
        .all()
    )

    # 전체 Work Items 목록 (최근 20건)
    all_items = (
        db.query(WorkItem)
        .filter(WorkItem.github_repo == github_repo)
        .order_by(WorkItem.updated_at.desc())
        .limit(20)
        .all()
    )

    return _render(
        "project_detail.html",
        project_name=project_name,
        github_repo=github_repo,
        work_stats=work_stats,
        trend=trend,
        plan_info=plan_info,
        plans=plans,
        all_items=all_items,
        current_period=period_type,
        active_page="projects",
    )
