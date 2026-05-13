"""
Claude 세션 로그 Pydantic 스키마
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from ..models.session_log import SessionSource, PendingStatus


# ============================================================
# Sub-resources
# ============================================================

class SessionItemResponse(BaseModel):
    id: int
    seq: int
    title: str
    content: Optional[str]

    model_config = {"from_attributes": True}


class SessionPendingResponse(BaseModel):
    id: int
    content: str
    status: PendingStatus
    work_item_id: Optional[int]
    resolved_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionCommitResponse(BaseModel):
    id: int
    repo: str
    commit_sha: str
    commit_message: Optional[str]
    committed_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ============================================================
# Session list / detail
# ============================================================

class SessionListResponse(BaseModel):
    id: int
    session_id: str
    project_name: str
    git_branch: Optional[str]
    topic: str
    document_no: Optional[str]
    started_at: datetime
    ended_at: datetime
    source: SessionSource
    duration_min: int
    commit_count: int
    message_count: int
    pending_open_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionDetailResponse(BaseModel):
    id: int
    session_id: str
    project_name: str
    cwd: Optional[str]
    git_branch: Optional[str]
    topic: str
    document_no: Optional[str]
    started_at: datetime
    ended_at: datetime
    summary_md: Optional[str]
    source: SessionSource
    duration_min: int
    commit_count: int
    message_count: int
    items: list[SessionItemResponse] = []
    pending: list[SessionPendingResponse] = []
    commits: list[SessionCommitResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ============================================================
# Mutation requests
# ============================================================

class IngestRequest(BaseModel):
    """Stop hook 또는 수동 호출용 ingest 요청"""
    session_id: Optional[str] = Field(default=None, description="UUID; transcript_path 미지정 시 필수")
    transcript_path: Optional[str] = Field(default=None, description="JSONL 파일 절대경로")
    dry_run: bool = False


class IngestResponse(BaseModel):
    status: str  # "registered" | "skipped" | "duplicate" | "error"
    message: str
    session_id: Optional[int] = None
    document_no: Optional[str] = None


class PendingApproveRequest(BaseModel):
    """미결사항 → work_items 등록"""
    title_override: Optional[str] = Field(default=None, max_length=500)
    summary: Optional[str] = None
    category: Optional[str] = Field(default="required", description="planned|required|in_progress")


class PendingActionResponse(BaseModel):
    pending_id: int
    status: PendingStatus
    work_item_id: Optional[int] = None
