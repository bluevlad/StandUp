"""
개발 플랜 API 엔드포인트
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from ....core.database import get_db
from ....models.dev_plan import PlanStatus
from ....schemas.dev_plan import (
    DevPlanCreate, DevPlanUpdate, DevPlanResponse, DevPlanListResponse,
    DevPlanItemCreate, DevPlanItemUpdate, DevPlanItemResponse,
)
from ....services.dev_plan_service import get_dev_plan_service

router = APIRouter(prefix="/dev-plans", tags=["dev-plans"])


# ------------------------------------------------------------------
# Plans
# ------------------------------------------------------------------

@router.get("", response_model=list[DevPlanListResponse])
def list_plans(
    project_name: str = Query(default=None),
    status: str = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """개발 플랜 목록"""
    service = get_dev_plan_service()
    plan_status = PlanStatus(status) if status else None
    plans = service.get_plans(db, project_name=project_name, status=plan_status, limit=limit, offset=offset)

    result = []
    for p in plans:
        result.append(DevPlanListResponse(
            id=p.id,
            project_name=p.project_name,
            github_repo=p.github_repo,
            title=p.title,
            status=p.status,
            total_phases=p.total_phases,
            current_phase=p.current_phase,
            progress_pct=p.progress_pct,
            completion_pct=p.completion_pct,
            quality_score=p.quality_score,
            started_at=p.started_at,
            target_date=p.target_date,
            item_count=len(p.items),
        ))
    return result


@router.get("/summary")
def get_project_summary(db: Session = Depends(get_db)):
    """프로젝트별 종합 메트릭 (대시보드용)"""
    service = get_dev_plan_service()
    return {
        "overall": service.get_overall_metrics(db),
        "projects": service.get_project_summary(db),
    }


@router.get("/{plan_id}", response_model=DevPlanResponse)
def get_plan(plan_id: int, db: Session = Depends(get_db)):
    """개발 플랜 상세"""
    service = get_dev_plan_service()
    plan = service.get_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="플랜을 찾을 수 없습니다")
    return plan


@router.post("", response_model=DevPlanResponse, status_code=201)
def create_plan(data: DevPlanCreate, db: Session = Depends(get_db)):
    """개발 플랜 생성"""
    service = get_dev_plan_service()
    plan_data = data.model_dump()
    items_data = plan_data.pop("items", [])
    # enum → value 변환
    if "status" in plan_data and plan_data["status"]:
        plan_data["status"] = plan_data["status"]
    plan_data["items"] = [
        {k: v for k, v in item.items() if v is not None}
        for item in items_data
    ]
    plan = service.create_plan(db, plan_data)
    return plan


@router.patch("/{plan_id}", response_model=DevPlanResponse)
def update_plan(plan_id: int, data: DevPlanUpdate, db: Session = Depends(get_db)):
    """개발 플랜 수정"""
    service = get_dev_plan_service()
    update_data = data.model_dump(exclude_unset=True)
    plan = service.update_plan(db, plan_id, update_data)
    if not plan:
        raise HTTPException(status_code=404, detail="플랜을 찾을 수 없습니다")
    # 상세 재조회 (items 포함)
    plan = service.get_plan(db, plan_id)
    return plan


@router.delete("/{plan_id}", status_code=204)
def delete_plan(plan_id: int, db: Session = Depends(get_db)):
    """개발 플랜 삭제"""
    service = get_dev_plan_service()
    if not service.delete_plan(db, plan_id):
        raise HTTPException(status_code=404, detail="플랜을 찾을 수 없습니다")


# ------------------------------------------------------------------
# Plan Items
# ------------------------------------------------------------------

@router.post("/{plan_id}/items", response_model=DevPlanItemResponse, status_code=201)
def create_item(plan_id: int, data: DevPlanItemCreate, db: Session = Depends(get_db)):
    """플랜 항목 추가"""
    service = get_dev_plan_service()
    item_data = data.model_dump(exclude_unset=True)
    item = service.create_item(db, plan_id, item_data)
    if not item:
        raise HTTPException(status_code=404, detail="플랜을 찾을 수 없습니다")
    return item


@router.patch("/items/{item_id}", response_model=DevPlanItemResponse)
def update_item(item_id: int, data: DevPlanItemUpdate, db: Session = Depends(get_db)):
    """플랜 항목 수정"""
    service = get_dev_plan_service()
    update_data = data.model_dump(exclude_unset=True)
    item = service.update_item(db, item_id, update_data)
    if not item:
        raise HTTPException(status_code=404, detail="항목을 찾을 수 없습니다")
    return item


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int, db: Session = Depends(get_db)):
    """플랜 항목 삭제"""
    service = get_dev_plan_service()
    if not service.delete_item(db, item_id):
        raise HTTPException(status_code=404, detail="항목을 찾을 수 없습니다")


# ------------------------------------------------------------------
# Metrics 재계산
# ------------------------------------------------------------------

@router.post("/{plan_id}/recalculate", response_model=DevPlanResponse)
def recalculate(plan_id: int, db: Session = Depends(get_db)):
    """플랜 메트릭 재계산"""
    service = get_dev_plan_service()
    plan = service.get_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="플랜을 찾을 수 없습니다")
    service.recalculate_metrics(db, plan_id)
    plan = service.get_plan(db, plan_id)
    return plan
