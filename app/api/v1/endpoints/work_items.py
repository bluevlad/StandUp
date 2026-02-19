"""
업무 항목 API 엔드포인트
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ....core.database import get_db
from ....models.issue import WorkItem, ItemCategory, ItemStatus
from ....schemas.work_item import WorkItemResponse
from ....agents.qa_agent import get_qa_agent
from ....agents.tobe_agent import get_tobe_agent

router = APIRouter(prefix="/work-items", tags=["work-items"])


@router.get("", response_model=list[WorkItemResponse])
def list_work_items(
    category: ItemCategory = None,
    status: ItemStatus = None,
    repo: str = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """업무 항목 목록 조회"""
    query = db.query(WorkItem).order_by(WorkItem.updated_at.desc())
    if category:
        query = query.filter(WorkItem.category == category)
    if status:
        query = query.filter(WorkItem.status == status)
    if repo:
        query = query.filter(WorkItem.github_repo == repo)
    return query.offset(offset).limit(limit).all()


@router.post("/scan")
def trigger_scan():
    """QA-Agent + Tobe-Agent 수동 스캔 트리거"""
    qa = get_qa_agent()
    tobe = get_tobe_agent()
    qa.run()
    tobe.run()
    return {"message": "스캔이 완료되었습니다."}
