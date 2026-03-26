"""
개발 플랜 Pydantic 스키마
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from ..models.dev_plan import PlanStatus, PlanItemStatus, PlanItemPriority


# ============================================================
# DevPlanItem
# ============================================================

class DevPlanItemCreate(BaseModel):
    phase: int = 1
    phase_title: Optional[str] = None
    sort_order: int = 0
    title: str = Field(..., max_length=500)
    description: Optional[str] = None
    priority: PlanItemPriority = PlanItemPriority.P2
    status: PlanItemStatus = PlanItemStatus.TODO
    weight: float = 1.0
    progress_pct: float = 0.0
    linked_issue_number: Optional[int] = None
    linked_issue_url: Optional[str] = None
    linked_pr_number: Optional[int] = None


class DevPlanItemUpdate(BaseModel):
    phase: Optional[int] = None
    phase_title: Optional[str] = None
    sort_order: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[PlanItemPriority] = None
    status: Optional[PlanItemStatus] = None
    weight: Optional[float] = None
    progress_pct: Optional[float] = None
    has_tests: Optional[int] = None
    has_review: Optional[int] = None
    has_docs: Optional[int] = None
    bug_count: Optional[int] = None
    linked_issue_number: Optional[int] = None
    linked_issue_url: Optional[str] = None
    linked_commits: Optional[str] = None
    linked_pr_number: Optional[int] = None


class DevPlanItemResponse(BaseModel):
    id: int
    plan_id: int
    phase: int
    phase_title: Optional[str]
    sort_order: int
    title: str
    description: Optional[str]
    priority: PlanItemPriority
    status: PlanItemStatus
    weight: float
    progress_pct: float
    has_tests: int
    has_review: int
    has_docs: int
    bug_count: int
    linked_issue_number: Optional[int]
    linked_issue_url: Optional[str]
    linked_commits: Optional[str]
    linked_pr_number: Optional[int]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ============================================================
# DevPlan
# ============================================================

class DevPlanCreate(BaseModel):
    project_name: str = Field(..., max_length=200)
    github_repo: Optional[str] = None
    title: str = Field(..., max_length=500)
    description: Optional[str] = None
    status: PlanStatus = PlanStatus.ACTIVE
    total_phases: int = 1
    current_phase: int = 1
    started_at: Optional[datetime] = None
    target_date: Optional[datetime] = None
    items: list[DevPlanItemCreate] = []


class DevPlanUpdate(BaseModel):
    project_name: Optional[str] = None
    github_repo: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[PlanStatus] = None
    total_phases: Optional[int] = None
    current_phase: Optional[int] = None
    started_at: Optional[datetime] = None
    target_date: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class DevPlanResponse(BaseModel):
    id: int
    project_name: str
    github_repo: Optional[str]
    title: str
    description: Optional[str]
    status: PlanStatus
    total_phases: int
    current_phase: int
    progress_pct: float
    completion_pct: float
    quality_score: float
    started_at: Optional[datetime]
    target_date: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    items: list[DevPlanItemResponse] = []

    model_config = {"from_attributes": True}


class DevPlanListResponse(BaseModel):
    id: int
    project_name: str
    github_repo: Optional[str]
    title: str
    status: PlanStatus
    total_phases: int
    current_phase: int
    progress_pct: float
    completion_pct: float
    quality_score: float
    started_at: Optional[datetime]
    target_date: Optional[datetime]
    item_count: int = 0

    model_config = {"from_attributes": True}


# ============================================================
# 프로젝트 요약 (대시보드용)
# ============================================================

class PhaseMetrics(BaseModel):
    """Phase별 메트릭"""
    phase: int
    phase_title: Optional[str]
    total_items: int
    done_items: int
    progress_pct: float
    completion_pct: float


class ProjectMetrics(BaseModel):
    """프로젝트별 종합 메트릭"""
    project_name: str
    github_repo: Optional[str]
    plan_count: int
    total_items: int
    done_items: int
    progress_pct: float
    completion_pct: float
    quality_score: float
    active_plan_title: Optional[str]
    phases: list[PhaseMetrics] = []
