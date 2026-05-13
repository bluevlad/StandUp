"""
Claude Code 세션 transcript → claude_sessions DB ingest CLI

표준: Claude-Opus-bluevlad/standards/claude-code/SESSION_LOG_FORMAT.md

사용:
  # 단일 세션
  python -m scripts.ingest_claude_session --session-id <UUID> --dry-run
  # 최근 24시간 내 모든 세션 자동 스캔
  python -m scripts.ingest_claude_session --since-hours 24 --dry-run
  # 실제 등록
  python -m scripts.ingest_claude_session --since-hours 24

임계값:
  - 세션 길이 >= 30분 OR git 커밋 >= 1건 만 등록 (둘 다 미달 시 skip)

Phase 1 한계:
  - LLM 요약 없음 → 주제는 첫 사용자 메시지 80자, 회의 내용은 커밋 메시지 + tool_use 액션 카운트
  - Phase 3 에서 Ollama 요약 + 마스킹 룰 추가 예정
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------

def iter_transcript(jsonl_path: Path) -> Iterator[dict]:
    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def extract_text(msg) -> str:
    """user/assistant message 의 content 에서 텍스트 부분만 결합"""
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


def parse_session(jsonl_path: Path) -> dict | None:
    """transcript JSONL → 세션 메타데이터 dict"""
    started_at = None
    ended_at = None
    cwd = None
    git_branch = None
    session_id = None
    first_user_msg = None
    user_msg_count = 0
    assistant_msg_count = 0
    tool_use_count = 0
    pending_candidates: list[str] = []

    for event in iter_transcript(jsonl_path):
        ts = parse_iso(event.get("timestamp", ""))
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
            text = extract_text(event.get("message"))
            if first_user_msg is None and text:
                first_user_msg = text
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
        "user_msg_count": user_msg_count,
        "assistant_msg_count": assistant_msg_count,
        "tool_use_count": tool_use_count,
        "pending_candidates": list(dict.fromkeys(pending_candidates)),  # de-dup
    }


# ---------------------------------------------------------------------------
# Project name resolution
# ---------------------------------------------------------------------------

def resolve_project_name(cwd: str | None) -> str | None:
    if not cwd:
        return None
    parts = Path(cwd).parts
    for proj in TARGET_PROJECTS:
        if proj in parts:
            return proj
    # fallback: parent dir name under ~/GIT/
    for i, part in enumerate(parts):
        if part == "GIT" and i + 1 < len(parts):
            return parts[i + 1]
    return None


# ---------------------------------------------------------------------------
# Git commit mapping
# ---------------------------------------------------------------------------

def collect_commits(repo_path: Path, since: datetime, until: datetime) -> list[dict]:
    if not repo_path.exists() or not (repo_path / ".git").exists():
        return []
    fmt = "%H%x1f%cI%x1f%s"
    cmd = [
        "git", "-C", str(repo_path),
        "log",
        f"--since={since.isoformat()}",
        f"--until={until.isoformat()}",
        f"--pretty=format:{fmt}",
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
            "committed_at": parse_iso(iso),
            "message": msg,
        })
    return commits


# ---------------------------------------------------------------------------
# Document number generator
# ---------------------------------------------------------------------------

def gen_document_no(db, project: str, started_at: datetime) -> str:
    from app.models.session_log import ClaudeSession
    date_str = started_at.strftime("%Y%m%d")
    prefix = f"CS-{date_str}-{project}-"
    existing = (
        db.query(ClaudeSession)
        .filter(ClaudeSession.document_no.like(f"{prefix}%"))
        .count()
    )
    return f"{prefix}{existing + 1:03d}"


# ---------------------------------------------------------------------------
# Summary builder (Phase 1: rule-based)
# ---------------------------------------------------------------------------

def build_summary(parsed: dict, commits: list[dict]) -> tuple[str, list[tuple[int, str, str]]]:
    """
    회의 내용 항목 리스트 + Markdown 본문 생성.
    Phase 1: 커밋 메시지 N개를 회의 내용 N개로 변환.
              커밋이 없으면 tool_use 카운트와 메시지 수로 단일 항목 생성.
    """
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


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def should_register(parsed: dict, commits: list[dict]) -> bool:
    return parsed["duration_min"] >= MIN_DURATION_MIN or len(commits) >= MIN_COMMITS


def ingest_one(db, jsonl_path: Path, dry_run: bool = False) -> str:
    from app.models.session_log import (
        ClaudeSession, SessionItem, SessionPending, SessionCommit, SessionSource,
    )
    parsed = parse_session(jsonl_path)
    if not parsed:
        return f"SKIP (parse fail): {jsonl_path.name}"

    project = resolve_project_name(parsed["cwd"])
    if not project:
        return f"SKIP (no project): {jsonl_path.name} cwd={parsed['cwd']}"

    repo_path = Path(parsed["cwd"]) if parsed["cwd"] else None
    commits = collect_commits(repo_path, parsed["started_at"], parsed["ended_at"]) if repo_path else []

    if not should_register(parsed, commits):
        return (
            f"SKIP (below threshold): {jsonl_path.name} "
            f"duration={parsed['duration_min']}min commits={len(commits)}"
        )

    existing = db.query(ClaudeSession).filter_by(session_id=parsed["session_id"]).first()
    if existing:
        return f"SKIP (already ingested): {jsonl_path.name} → session id={existing.id}"

    summary_md, items = build_summary(parsed, commits)

    if dry_run:
        return (
            f"DRY-RUN: would register {jsonl_path.name}\n"
            f"  project={project} duration={parsed['duration_min']}min commits={len(commits)}\n"
            f"  pending={len(parsed['pending_candidates'])}\n"
            f"--- summary preview (head) ---\n"
            f"{summary_md[:500]}\n"
        )

    document_no = gen_document_no(db, project, parsed["started_at"])
    session = ClaudeSession(
        session_id=parsed["session_id"],
        project_name=project,
        cwd=parsed["cwd"],
        git_branch=parsed["git_branch"],
        topic=parsed["first_user_msg"].split("\n", 1)[0][:480],
        document_no=document_no,
        started_at=parsed["started_at"].replace(tzinfo=None),
        ended_at=parsed["ended_at"].replace(tzinfo=None),
        summary_md=summary_md,
        source=SessionSource.AUTO,
        duration_min=parsed["duration_min"],
        commit_count=len(commits),
        message_count=parsed["user_msg_count"] + parsed["assistant_msg_count"],
    )
    db.add(session)
    db.flush()

    for seq, title, content in items:
        db.add(SessionItem(session_id=session.id, seq=seq, title=title, content=content))

    for p in parsed["pending_candidates"]:
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
    return (
        f"OK: {jsonl_path.name} → id={session.id} document_no={document_no} "
        f"items={len(items)} pending={len(parsed['pending_candidates'])} commits={len(commits)}"
    )


def iter_targets(session_id: str | None, since_hours: int | None) -> Iterator[Path]:
    if not CLAUDE_PROJECTS_DIR.exists():
        return
    if session_id:
        for p in CLAUDE_PROJECTS_DIR.rglob(f"{session_id}.jsonl"):
            yield p
        return
    cutoff = None
    if since_hours:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    for p in CLAUDE_PROJECTS_DIR.rglob("*.jsonl"):
        if cutoff:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                continue
        yield p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session-id", help="특정 세션 UUID 만 처리")
    ap.add_argument("--since-hours", type=int, help="최근 N 시간 내 수정된 transcript 만 처리")
    ap.add_argument("--dry-run", action="store_true", help="DB 변경 없이 결과만 출력")
    args = ap.parse_args()

    if not args.session_id and not args.since_hours:
        ap.error("--session-id 또는 --since-hours 중 하나는 필수")

    targets = list(iter_targets(args.session_id, args.since_hours))
    if not targets:
        print("대상 세션 transcript 없음", file=sys.stderr)
        return 1

    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        for path in targets:
            try:
                msg = ingest_one(db, path, dry_run=args.dry_run)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                msg = f"ERROR: {path.name} {exc!r}"
            print(msg)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
