"""
Claude 세션 로그 서비스
- transcript JSONL 파싱 + git 커밋 매핑 (ingest)
- 회의 내용/미결사항 추출
- 미결사항 승인 → work_items 등록

표준: Claude-Opus-bluevlad/standards/claude-code/SESSION_LOG_FORMAT.md
"""

import json
import logging
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from sqlalchemy.orm import Session, joinedload

from ..models.session_log import (
    ClaudeSession, SessionItem, SessionPending, SessionCommit,
    SessionSource, PendingStatus,
)
from ..models.issue import WorkItem, ItemCategory, ItemStatus
from .session_summarizer import summarize_session

logger = logging.getLogger(__name__)

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
MIN_DURATION_MIN = 30
MIN_COMMITS = 1
PENDING_KEYWORDS = ("TODO", "todo", "미결", "나중에", "이후", "다음에", "follow-up", "FIXME")
TARGET_PROJECTS = [
    "hopenvision", "AllergyInsight", "EduFit", "NewsLetterPlatform",
    "unmong-main", "StandUp", "Autonomous-QA-Agent", "Auto-Tobe-Agent",
    "Claude-Opus-bluevlad", "InfraWatcher", "QA-Dashboard", "CompanyAnalyzer",
    "LogAnalyzer", "OpsConsole",
]


# ============================================================
# Transcript parsing (pure functions, no DB)
# ============================================================

def _iter_transcript(jsonl_path: Path) -> Iterator[dict]:
    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_text(msg) -> str:
    if isinstance(msg, str):
        return msg
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text" and "text" in part:
                        parts.append(part["text"])
                    elif "text" in part:
                        parts.append(str(part["text"]))
            return "\n".join(parts)
    return ""


def parse_transcript(jsonl_path: Path) -> dict | None:
    started_at = ended_at = None
    cwd = git_branch = session_id = None
    first_user_msg = None
    user_msg_count = assistant_msg_count = tool_use_count = 0
    pending_candidates: list[str] = []
    user_messages: list[str] = []

    for event in _iter_transcript(jsonl_path):
        ts = _parse_iso(event.get("timestamp", ""))
        if ts:
            if started_at is None or ts < started_at:
                started_at = ts
            if ended_at is None or ts > ended_at:
                ended_at = ts
        if not session_id:
            session_id = event.get("sessionId")
        if not cwd and event.get("cwd"):
            cwd = event["cwd"]
        if not git_branch and event.get("gitBranch"):
            git_branch = event["gitBranch"]

        etype = event.get("type")
        if etype == "user":
            user_msg_count += 1
            text = _extract_text(event.get("message"))
            if first_user_msg is None and text:
                first_user_msg = text
            if text:
                user_messages.append(text)
            for kw in PENDING_KEYWORDS:
                if kw in text:
                    for line in text.splitlines():
                        if kw in line and len(line) < 300:
                            pending_candidates.append(line.strip())
        elif etype == "assistant":
            assistant_msg_count += 1
            message = event.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "tool_use":
                            tool_use_count += 1

    if not session_id or not started_at or not ended_at:
        return None

    duration_min = int((ended_at - started_at).total_seconds() // 60)
    return {
        "session_id": session_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_min": duration_min,
        "cwd": cwd,
        "git_branch": git_branch,
        "first_user_msg": first_user_msg or "(no user message)",
        "user_messages": user_messages,
        "user_msg_count": user_msg_count,
        "assistant_msg_count": assistant_msg_count,
        "tool_use_count": tool_use_count,
        "pending_candidates": list(dict.fromkeys(pending_candidates)),
    }


def resolve_project_name(cwd: str | None) -> str | None:
    if not cwd:
        return None
    parts = Path(cwd).parts
    for proj in TARGET_PROJECTS:
        if proj in parts:
            return proj
    for i, part in enumerate(parts):
        if part == "GIT" and i + 1 < len(parts):
            return parts[i + 1]
    return None


def collect_commits(repo_path: Path, since: datetime, until: datetime) -> list[dict]:
    if not repo_path.exists() or not (repo_path / ".git").exists():
        return []
    cmd = [
        "git", "-C", str(repo_path),
        "log",
        f"--since={since.isoformat()}",
        f"--until={until.isoformat()}",
        "--pretty=format:%H\x1f%cI\x1f%s",
        "--no-merges",
    ]
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return []
    commits = []
    for line in out.strip().splitlines():
        sha, iso, msg = (line.split("\x1f", 2) + ["", "", ""])[:3]
        commits.append({
            "sha": sha,
            "committed_at": _parse_iso(iso),
            "message": msg,
        })
    return commits


def should_register(parsed: dict, commits: list[dict]) -> bool:
    return parsed["duration_min"] >= MIN_DURATION_MIN or len(commits) >= MIN_COMMITS


def _render_summary_md(
    topic: str,
    started_at: datetime,
    ended_at: datetime,
    items: list[tuple[int, str, str]],
    pending: list[str],
) -> str:
    lines = [
        "-회 의 록-",
        "",
        f"-주제 및 안건 : {topic}",
        f"-일시 : {started_at.isoformat()} ~ {ended_at.isoformat()}",
        "-회의 내용 :",
    ]
    for seq, title, content in items:
        lines.append(f"   {seq}. {title}")
        if content:
            lines.append(f"      {content}")
    lines.append("-미결사항 :")
    if pending:
        for p in pending:
            lines.append(f"   - {p}")
    else:
        lines.append("   - (없음)")
    return "\n".join(lines)


def build_summary(parsed: dict, commits: list[dict]) -> tuple[str, list[tuple[int, str, str]]]:
    items: list[tuple[int, str, str]] = []
    if commits:
        for i, c in enumerate(commits, start=1):
            msg = c["message"] or "(no commit message)"
            title = msg.split("\n", 1)[0][:200]
            items.append((i, title, f"commit `{c['sha'][:8]}` @ {c['committed_at']}"))
    else:
        items.append((
            1,
            "코드 변경 없는 토론/조사 세션",
            f"user msgs={parsed['user_msg_count']}, "
            f"assistant msgs={parsed['assistant_msg_count']}, "
            f"tool_use={parsed['tool_use_count']}",
        ))

    topic = parsed["first_user_msg"].split("\n", 1)[0][:200]
    lines = [
        "-회 의 록-",
        "",
        f"-주제 및 안건 : {topic}",
        f"-일시 : {parsed['started_at'].isoformat()} ~ {parsed['ended_at'].isoformat()}",
        "-회의 내용 :",
    ]
    for seq, title, content in items:
        lines.append(f"   {seq}. {title}")
        if content:
            lines.append(f"      {content}")
    lines.append("-미결사항 :")
    if parsed["pending_candidates"]:
        for p in parsed["pending_candidates"]:
            lines.append(f"   - {p}")
    else:
        lines.append("   - (없음)")
    return "\n".join(lines), items


# ============================================================
# Service class (DB-bound)
# ============================================================

class SessionLogService:
    """Claude 세션 로그 서비스"""

    # -------------------- Queries --------------------

    def list_sessions(
        self,
        db: Session,
        project_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        query = (
            db.query(ClaudeSession)
            .order_by(ClaudeSession.started_at.desc())
        )
        if project_name:
            query = query.filter(ClaudeSession.project_name == project_name)
        rows = query.offset(offset).limit(limit).all()

        out: list[dict] = []
        for s in rows:
            pending_open = (
                db.query(SessionPending)
                .filter(
                    SessionPending.session_id == s.id,
                    SessionPending.status == PendingStatus.OPEN,
                )
                .count()
            )
            out.append({
                "id": s.id,
                "session_id": s.session_id,
                "project_name": s.project_name,
                "git_branch": s.git_branch,
                "topic": s.topic,
                "document_no": s.document_no,
                "started_at": s.started_at,
                "ended_at": s.ended_at,
                "source": s.source,
                "duration_min": s.duration_min,
                "commit_count": s.commit_count,
                "message_count": s.message_count,
                "pending_open_count": pending_open,
                "created_at": s.created_at,
            })
        return out

    def get_session_detail(self, db: Session, session_pk: int) -> ClaudeSession | None:
        return (
            db.query(ClaudeSession)
            .options(
                joinedload(ClaudeSession.items),
                joinedload(ClaudeSession.pending),
                joinedload(ClaudeSession.commits),
            )
            .filter(ClaudeSession.id == session_pk)
            .first()
        )

    def count_sessions(self, db: Session, project_name: str | None = None) -> int:
        query = db.query(ClaudeSession)
        if project_name:
            query = query.filter(ClaudeSession.project_name == project_name)
        return query.count()

    # -------------------- Ingest --------------------

    def _gen_document_no(self, db: Session, project: str, started_at: datetime) -> str:
        date_str = started_at.strftime("%Y%m%d")
        prefix = f"CS-{date_str}-{project}-"
        existing = (
            db.query(ClaudeSession)
            .filter(ClaudeSession.document_no.like(f"{prefix}%"))
            .count()
        )
        return f"{prefix}{existing + 1:03d}"

    def ingest_from_jsonl(
        self,
        db: Session,
        jsonl_path: Path,
        source: SessionSource = SessionSource.AUTO,
        dry_run: bool = False,
    ) -> dict:
        """
        결과 dict:
          status: 'registered' | 'skipped' | 'duplicate' | 'parse_failed'
          message: 사람이 읽을 수 있는 설명
          session_id (PK): 등록된 경우만
          document_no: 등록된 경우만
        """
        parsed = parse_transcript(jsonl_path)
        if not parsed:
            return {"status": "parse_failed", "message": f"parse fail: {jsonl_path.name}"}

        project = resolve_project_name(parsed["cwd"])
        if not project:
            return {
                "status": "skipped",
                "message": f"no project mapped for cwd={parsed['cwd']}",
            }

        repo_path = Path(parsed["cwd"]) if parsed["cwd"] else None
        commits = (
            collect_commits(repo_path, parsed["started_at"], parsed["ended_at"])
            if repo_path else []
        )

        if not should_register(parsed, commits):
            return {
                "status": "skipped",
                "message": (
                    f"below threshold: duration={parsed['duration_min']}min "
                    f"commits={len(commits)}"
                ),
            }

        existing = (
            db.query(ClaudeSession)
            .filter_by(session_id=parsed["session_id"])
            .first()
        )
        if existing:
            return {
                "status": "duplicate",
                "message": f"already ingested as id={existing.id}",
                "session_id": existing.id,
                "document_no": existing.document_no,
            }

        # 1) Rule-based 베이스라인
        summary_md, items = build_summary(parsed, commits)
        topic = parsed["first_user_msg"].split("\n", 1)[0][:480]
        pending_list = list(parsed["pending_candidates"])
        llm_used = False

        # 2) LLM 보강 (실패 시 베이스라인 유지)
        llm_out = summarize_session(parsed, commits, parsed.get("user_messages", []))
        if llm_out:
            llm_used = True
            if llm_out.get("topic"):
                topic = llm_out["topic"][:480]
            if llm_out.get("items"):
                items = [
                    (i + 1, it["title"], it.get("content") or "")
                    for i, it in enumerate(llm_out["items"])
                ]
            # pending 은 LLM 결과 + rule-based 결합 (중복 제거)
            seen: set[str] = set()
            merged_pending: list[str] = []
            for p in (llm_out.get("pending") or []) + pending_list:
                key = p.strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    merged_pending.append(p.strip())
            pending_list = merged_pending

            # 회의록 본문 재생성 (LLM 결과 반영)
            summary_md = _render_summary_md(
                topic=topic,
                started_at=parsed["started_at"],
                ended_at=parsed["ended_at"],
                items=items,
                pending=pending_list,
            )

        if dry_run:
            return {
                "status": "registered",
                "message": "(dry-run) would register" + (" (LLM)" if llm_used else " (rule)"),
                "document_no": None,
            }

        document_no = self._gen_document_no(db, project, parsed["started_at"])
        session = ClaudeSession(
            session_id=parsed["session_id"],
            project_name=project,
            cwd=parsed["cwd"],
            git_branch=parsed["git_branch"],
            topic=topic,
            document_no=document_no,
            started_at=parsed["started_at"].replace(tzinfo=None),
            ended_at=parsed["ended_at"].replace(tzinfo=None),
            summary_md=summary_md,
            source=SessionSource.HYBRID if llm_used else source,
            duration_min=parsed["duration_min"],
            commit_count=len(commits),
            message_count=parsed["user_msg_count"] + parsed["assistant_msg_count"],
        )
        db.add(session)
        db.flush()

        for seq, title, content in items:
            db.add(SessionItem(session_id=session.id, seq=seq, title=title, content=content))
        for p in pending_list:
            db.add(SessionPending(session_id=session.id, content=p))
        for c in commits:
            db.add(SessionCommit(
                session_id=session.id,
                repo=project,
                commit_sha=c["sha"],
                commit_message=c["message"],
                committed_at=c["committed_at"].replace(tzinfo=None) if c["committed_at"] else None,
            ))
        db.commit()

        return {
            "status": "registered",
            "message": (
                f"id={session.id} items={len(items)} "
                f"pending={len(pending_list)} commits={len(commits)}"
                + (" (LLM)" if llm_used else " (rule)")
            ),
            "session_id": session.id,
            "document_no": document_no,
        }

    def ingest_recent(self, db: Session, since_hours: int) -> list[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        results: list[dict] = []
        if not CLAUDE_PROJECTS_DIR.exists():
            return results
        for path in CLAUDE_PROJECTS_DIR.rglob("*.jsonl"):
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                continue
            try:
                results.append({"file": path.name, **self.ingest_from_jsonl(db, path)})
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                results.append({"file": path.name, "status": "error", "message": repr(exc)})
        return results

    # -------------------- Pending approval --------------------

    def approve_pending(
        self,
        db: Session,
        pending_id: int,
        title_override: str | None = None,
        summary: str | None = None,
        category: str = "required",
    ) -> SessionPending | None:
        pending = db.query(SessionPending).filter_by(id=pending_id).first()
        if not pending:
            return None
        if pending.status != PendingStatus.OPEN:
            return pending  # 이미 처리됨 — 그대로 반환

        session = db.query(ClaudeSession).filter_by(id=pending.session_id).first()
        if not session:
            return None

        try:
            cat_enum = ItemCategory(category)
        except ValueError:
            cat_enum = ItemCategory.REQUIRED

        work_item = WorkItem(
            github_repo=session.project_name,
            category=cat_enum,
            status=ItemStatus.OPEN,
            title=(title_override or pending.content)[:500],
            summary=summary or (
                f"Claude 세션 미결사항 → 문서번호 {session.document_no}\n"
                f"원문: {pending.content}"
            ),
        )
        db.add(work_item)
        db.flush()

        pending.work_item_id = work_item.id
        pending.status = PendingStatus.REGISTERED
        pending.resolved_at = datetime.utcnow()
        db.commit()
        db.refresh(pending)
        return pending

    def dismiss_pending(self, db: Session, pending_id: int) -> SessionPending | None:
        pending = db.query(SessionPending).filter_by(id=pending_id).first()
        if not pending:
            return None
        if pending.status == PendingStatus.OPEN:
            pending.status = PendingStatus.DISMISSED
            pending.resolved_at = datetime.utcnow()
            db.commit()
            db.refresh(pending)
        return pending


_service_singleton: SessionLogService | None = None


def get_session_log_service() -> SessionLogService:
    global _service_singleton
    if _service_singleton is None:
        _service_singleton = SessionLogService()
    return _service_singleton
