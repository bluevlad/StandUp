"""
보고서 API 엔드포인트
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ....core.database import get_db
from ....models.report import ReportType
from ....schemas.report import ReportResponse, ReportListResponse
from ....services.report_service import get_report_service
from ....agents.report_agent import get_report_agent

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=list[ReportListResponse])
def list_reports(
    report_type: ReportType = None,
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """보고서 목록 조회"""
    service = get_report_service()
    reports = service.get_reports(db, report_type=report_type, limit=limit, offset=offset)
    result = []
    for r in reports:
        item = ReportListResponse.model_validate(r)
        item.item_count = len(r.items)
        result.append(item)
    return result


@router.get("/{report_id}", response_model=ReportResponse)
def get_report(report_id: int, db: Session = Depends(get_db)):
    """보고서 상세 조회"""
    service = get_report_service()
    report = service.get_report(db, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다.")
    return report


@router.post("/trigger/{report_type}")
def trigger_report(report_type: ReportType):
    """보고서 수동 생성/발송 트리거"""
    agent = get_report_agent()

    if report_type == ReportType.DAILY:
        agent.send_daily_report()
    elif report_type == ReportType.WEEKLY:
        agent.send_weekly_report()
    elif report_type == ReportType.MONTHLY:
        agent.send_monthly_report()

    return {"message": f"{report_type.value} 보고서 생성/발송이 트리거되었습니다."}
