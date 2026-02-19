"""
업무 항목 Pydantic 스키마
"""

from datetime import datetime
from pydantic import BaseModel

from ..models.issue import ItemCategory, ItemStatus


class WorkItemResponse(BaseModel):
    id: int
    github_repo: str
    github_issue_number: int | None
    github_issue_url: str | None
    category: ItemCategory
    status: ItemStatus
    title: str
    summary: str | None
    labels: str | None
    related_commits: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}
