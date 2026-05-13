"""
Claude 세션 회의록 API
- 목록/상세 조회
- Stop hook / 수동 ingest
- 미결사항 승인/거절
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Query, HTTPException, Body
from sqlalchemy.orm import Session

from ....core.database import get_db
from ....schemas.session_log import (
    SessionListResponse, SessionDetailResponse,
    IngestRequest, IngestResponse,
    PendingApproveRequest, PendingActionResponse,
)
from ....services.session_log_service import (
    get_session_log_service, CLAUDE_PROJECTS_DIR,
)

router = APIRouter(prefix="/claude-sessions", tags=["claude-sessions"])


# -------------------- Queries --------------------

@router.get("", response_model=list[SessionListResponse])
def list_sessions(
    project_name: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    service = get_session_log_service()
    return service.list_sessions(db, project_name=project_name, limit=limit, offset=offset)


@router.get("/{session_pk}", response_model=SessionDetailResponse)
def get_session(session_pk: int, db: Session = Depends(get_db)):
    service = get_session_log_service()
    session = service.get_session_detail(db, session_pk)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다")
    return session


# -------------------- Ingest --------------------

@router.post("/ingest", response_model=IngestResponse)
def ingest_session(payload: IngestRequest, db: Session = Depends(get_db)):
    """
    transcript JSONL 을 파싱하여 등록한다.
    - transcript_path 우선, 없으면 session_id 로 ~/.claude/projects/ 전체 검색
    """
    service = get_session_log_service()

    if payload.transcript_path:
        path = Path(payload.transcript_path)
    elif payload.session_id:
        matches = list(CLAUDE_PROJECTS_DIR.rglob(f"{payload.session_id}.jsonl"))
        if not matches:
            raise HTTPException(404, f"transcript not found for session_id={payload.session_id}")
        path = matches[0]
    else:
        raise HTTPException(400, "session_id 또는 transcript_path 중 하나는 필수")

    if not path.exists():
        raise HTTPException(404, f"transcript file not found: {path}")

    result = service.ingest_from_jsonl(db, path, dry_run=payload.dry_run)
    return IngestResponse(
        status=result["status"],
        message=result["message"],
        session_id=result.get("session_id"),
        document_no=result.get("document_no"),
    )


@router.post("/ingest/recent", response_model=list[dict])
def ingest_recent(
    since_hours: int = Query(default=24, ge=1, le=720),
    db: Session = Depends(get_db),
):
    """최근 N시간 내 수정된 transcript 일괄 ingest (수동 트리거)"""
    service = get_session_log_service()
    return service.ingest_recent(db, since_hours=since_hours)


# -------------------- Pending approval --------------------

@router.post(
    "/{session_pk}/pending/{pending_id}/approve",
    response_model=PendingActionResponse,
)
def approve_pending(
    session_pk: int,
    pending_id: int,
    payload: PendingApproveRequest = Body(default_factory=PendingApproveRequest),
    db: Session = Depends(get_db),
):
    service = get_session_log_service()
    pending = service.approve_pending(
        db,
        pending_id=pending_id,
        title_override=payload.title_override,
        summary=payload.summary,
        category=payload.category or "required",
    )
    if not pending:
        raise HTTPException(404, "pending 항목을 찾을 수 없습니다")
    return PendingActionResponse(
        pending_id=pending.id,
        status=pending.status,
        work_item_id=pending.work_item_id,
    )


@router.post(
    "/{session_pk}/pending/{pending_id}/dismiss",
    response_model=PendingActionResponse,
)
def dismiss_pending(
    session_pk: int,
    pending_id: int,
    db: Session = Depends(get_db),
):
    service = get_session_log_service()
    pending = service.dismiss_pending(db, pending_id=pending_id)
    if not pending:
        raise HTTPException(404, "pending 항목을 찾을 수 없습니다")
    return PendingActionResponse(
        pending_id=pending.id,
        status=pending.status,
        work_item_id=pending.work_item_id,
    )
