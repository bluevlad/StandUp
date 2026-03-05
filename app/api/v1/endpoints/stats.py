"""
통계 API 엔드포인트
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ....core.database import get_db
from ....services.stats_service import get_stats_service

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/summary")
def get_summary(
    period_type: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    date_from: datetime = None,
    date_to: datetime = None,
    db: Session = Depends(get_db),
):
    """기간별 요약 통계"""
    service = get_stats_service()
    return service.get_summary(db, period_type=period_type, date_from=date_from, date_to=date_to)


@router.get("/trend")
def get_trend(
    period_type: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    date_from: datetime = None,
    date_to: datetime = None,
    db: Session = Depends(get_db),
):
    """기간별 트렌드 데이터 (차트용)"""
    service = get_stats_service()
    return service.get_trend(db, period_type=period_type, date_from=date_from, date_to=date_to)


@router.get("/reports")
def get_report_stats(
    date_from: datetime = None,
    date_to: datetime = None,
    db: Session = Depends(get_db),
):
    """보고서 발송 통계"""
    service = get_stats_service()
    return service.get_report_stats(db, date_from=date_from, date_to=date_to)
