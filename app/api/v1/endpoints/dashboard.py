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
from ....models.insight import Newsletter, IngestionEvent
from ....services.report_service import get_report_service
from ....services.stats_service import get_stats_service
from ....services.dev_plan_service import get_dev_plan_service
from ....services.session_log_service import get_session_log_service
from ....models.dev_plan import DevPlan, PlanStatus, PlanItemStatus
from ....models.session_log import PendingStatus

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
    """대시보드 메인 (최근 보고서 + 프로젝트 현황)"""
    service = get_report_service()
    stats_svc = get_stats_service()
    dev_plan_svc = get_dev_plan_service()

    recent_reports = service.get_reports(db, limit=5)

    # TARGET_PROJECTS 기준 전체 기간 요약
    summary = stats_svc.get_target_projects_summary(db)

    # 프로젝트별 Work Items + Dev Plan 통합 데이터
    work_stats = stats_svc.get_all_projects_overview(db)
    plan_summary = dev_plan_svc.get_project_summary(db)
    overall = dev_plan_svc.get_overall_metrics(db)

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
        })

    return _render(
        "home.html",
        recent_reports=recent_reports,
        summary=summary,
        overall=overall,
        projects=projects,
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
    from ....services.hopenvision_proposal_service import get_ai_generated_plan_ids

    service = get_dev_plan_service()
    overall = service.get_overall_metrics(db)
    projects = service.get_project_summary(db)

    # 프로젝트별 플랜 목록 (상세 링크용) — AI 제안 DRAFT 도 노출
    all_plans = (
        db.query(DevPlan)
        .filter(DevPlan.status.in_(
            [PlanStatus.DRAFT, PlanStatus.ACTIVE, PlanStatus.COMPLETED]
        ))
        .order_by(DevPlan.project_name, DevPlan.updated_at.desc())
        .all()
    )
    plans_by_project: dict[str, list] = {}
    for plan in all_plans:
        plans_by_project.setdefault(plan.project_name, []).append(plan)

    ai_generated_plan_ids = get_ai_generated_plan_ids(db)

    return _render(
        "dev_plans.html",
        overall=overall,
        projects=projects,
        plans_by_project=plans_by_project,
        ai_generated_plan_ids=ai_generated_plan_ids,
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
    repo_name = proj_info.get("repo_name", proj_info["name"])

    # Work Items 통계 (repo_name으로 매칭)
    work_stats = stats_svc.get_project_work_stats(db, repo_name)

    # Work Items 추이
    trend = stats_svc.get_project_trend(db, repo_name, period_type)

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
        .filter(WorkItem.github_repo == repo_name)
        .order_by(WorkItem.updated_at.desc())
        .limit(20)
        .all()
    )

    return _render(
        "project_detail.html",
        project_name=project_name,
        github_repo=github_repo,
        repo_name=repo_name,
        work_stats=work_stats,
        trend=trend,
        plan_info=plan_info,
        plans=plans,
        all_items=all_items,
        current_period=period_type,
        active_page="projects",
    )


@router.get("/insights", response_class=HTMLResponse)
def insights_page(
    severity: str = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    cluster_days: int = Query(default=30, ge=7, le=120),
    db: Session = Depends(get_db),
):
    """Insight 통합 페이지 — ① Tech Digest + ② 토픽 클러스터 + ③ HopenVision 가이드 + ④ 기술 토픽 자동 제안"""
    from sqlalchemy import select
    from ....services.topic_cluster_service import get_topic_clusters
    from ....services.hopenvision_proposal_service import (
        list_tech_topic_proposals,
    )

    nl_q = select(Newsletter).order_by(Newsletter.created_at.desc()).limit(limit)
    newsletters = db.scalars(nl_q).all()

    # 각 뉴스레터의 source 이벤트 severity 분포 집계
    cards = []
    for nl in newsletters:
        sev_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "other": 0}
        if nl.source_event_ids:
            ev_rows = db.scalars(
                select(IngestionEvent.severity).where(
                    IngestionEvent.id.in_(nl.source_event_ids)
                )
            ).all()
            for sev in ev_rows:
                key = (sev or "other").lower()
                if key not in sev_counts:
                    key = "other"
                sev_counts[key] += 1
        cards.append({
            "id": str(nl.id),
            "period_start": nl.period_start,
            "period_end": nl.period_end,
            "headline": nl.headline,
            "subject": nl.subject,
            "created_at": nl.created_at,
            "sent_at": nl.sent_at,
            "source_count": len(nl.source_event_ids or []),
            "kpis": nl.kpis or {},
            "sev_counts": sev_counts,
        })

    if severity in ("critical", "high", "medium", "low"):
        cards = [c for c in cards if c["sev_counts"].get(severity, 0) > 0]

    # 섹션 ② 토픽 클러스터
    try:
        topic_clusters = get_topic_clusters(db, days=cluster_days)
    except Exception as exc:  # pgvector 미설치 / 데이터 없음 시 페이지는 유지
        import logging
        logging.getLogger(__name__).warning("topic clustering 실패: %s", exc)
        topic_clusters = []

    # 섹션 ④ 기술 토픽 자동 제안 (orchestrator 가 주간 합성 후 자동 생성)
    try:
        tech_trend_proposals = list_tech_topic_proposals(db, limit=10)
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("tech_trend proposals 조회 실패: %s", exc)
        tech_trend_proposals = []

    return _render(
        "insights.html",
        cards=cards,
        current_severity=severity or "all",
        topic_clusters=topic_clusters,
        cluster_days=cluster_days,
        tech_trend_proposals=tech_trend_proposals,
        active_page="insights",
    )


@router.get("/insights/topics/{cluster_key}/related", response_class=HTMLResponse)
def insights_topic_related(cluster_key: str, db: Session = Depends(get_db)):
    """HTMX 파셜: 클러스터 → 관련 과거 뉴스레터 청크."""
    from ....services.topic_cluster_service import get_related_newsletters
    related = get_related_newsletters(db, cluster_key, top_k=3)
    return _render("partials/topic_related.html", related=related)


@router.post("/insights/topics/{cluster_key}/hopenvision/generate",
             response_class=HTMLResponse)
def insights_hopenvision_generate(
    cluster_key: str,
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """HTMX: 토픽 클러스터 → HopenVision 적용 LLM 제안 생성/조회."""
    from ....services.hopenvision_proposal_service import generate_proposal
    try:
        result = generate_proposal(db, cluster_key, force=force)
    except ValueError as e:
        return _render("partials/hopenvision_proposal.html",
                       error=str(e), proposal=None)
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("hopenvision generate 실패")
        return _render("partials/hopenvision_proposal.html",
                       error=f"제안 생성 중 오류: {e}", proposal=None)
    return _render("partials/hopenvision_proposal.html",
                   proposal=result, error=None)


@router.post("/insights/proposals/{proposal_id}/accept",
             response_class=HTMLResponse)
def insights_hopenvision_accept(proposal_id: str, db: Session = Depends(get_db)):
    """HTMX: 제안 수락 → DevPlan 자동 초안 생성."""
    from ....services.hopenvision_proposal_service import accept_as_dev_plan
    try:
        plan = accept_as_dev_plan(db, proposal_id)
    except ValueError as e:
        html = f'<div style="color:#cf222e; font-size:12px;">{e}</div>'
        return HTMLResponse(content=html, status_code=400)
    href = f"{settings.root_path}/dashboard/dev-plans/{plan.id}"
    html = (
        f'<div style="color:#16a34a; font-size:12px; padding:8px 0;">'
        f'✓ DevPlan 초안 생성됨 — '
        f'<a href="{href}" style="color:#2563eb; text-decoration:underline;">'
        f'#{plan.id} {plan.title}</a></div>'
    )
    return HTMLResponse(content=html)


# =====================================================================
# Claude 세션 회의록
# =====================================================================

@router.get("/sessions", response_class=HTMLResponse)
def sessions_list(
    project_name: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    service = get_session_log_service()
    sessions = service.list_sessions(
        db, project_name=project_name, limit=limit, offset=offset
    )
    total = service.count_sessions(db, project_name=project_name)
    return _render(
        "sessions_list.html",
        sessions=sessions,
        total=total,
        current_project=project_name or "",
        limit=limit,
        offset=offset,
        active_page="sessions",
    )


@router.get("/sessions/{session_pk}", response_class=HTMLResponse)
def sessions_detail(session_pk: int, db: Session = Depends(get_db)):
    service = get_session_log_service()
    session = service.get_session_detail(db, session_pk)
    if not session:
        return HTMLResponse(content="<h1>세션을 찾을 수 없습니다</h1>", status_code=404)
    return _render(
        "sessions_detail.html",
        session=session,
        PendingStatus=PendingStatus,
        active_page="sessions",
    )
