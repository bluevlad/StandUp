"""
보고서 Pydantic 스키마
"""

from datetime import datetime
from pydantic import BaseModel

from ..models.report import ReportType, ReportStatus


class ReportItemResponse(BaseModel):
    id: int
    category: str
    project_name: str
    title: str
    detail: str | None
    source_type: str
    source_ref: str | None

    model_config = {"from_attributes": True}


class ReportResponse(BaseModel):
    id: int
    report_type: ReportType
    status: ReportStatus
    period_start: datetime
    period_end: datetime
    subject: str
    recipients: str
    generated_at: datetime
    sent_at: datetime | None
    retry_count: int
    items: list[ReportItemResponse] = []

    model_config = {"from_attributes": True}


class ReportListResponse(BaseModel):
    id: int
    report_type: ReportType
    status: ReportStatus
    period_start: datetime
    period_end: datetime
    subject: str
    generated_at: datetime
    sent_at: datetime | None
    item_count: int = 0

    model_config = {"from_attributes": True}
