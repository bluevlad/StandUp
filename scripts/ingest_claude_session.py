"""
Claude Code 세션 transcript → claude_sessions DB ingest CLI (얇은 래퍼)

서비스 로직은 app/services/session_log_service.py 에 위치.
표준: Claude-Opus-bluevlad/standards/claude-code/SESSION_LOG_FORMAT.md

사용:
  python -m scripts.ingest_claude_session --session-id <UUID> --dry-run
  python -m scripts.ingest_claude_session --since-hours 24 --dry-run
  python -m scripts.ingest_claude_session --since-hours 24
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session-id", help="특정 세션 UUID 만 처리")
    ap.add_argument("--since-hours", type=int, help="최근 N 시간 내 수정된 transcript 만 처리")
    ap.add_argument("--dry-run", action="store_true", help="DB 변경 없이 결과만 출력")
    args = ap.parse_args()

    if not args.session_id and not args.since_hours:
        ap.error("--session-id 또는 --since-hours 중 하나는 필수")

    from app.core.database import SessionLocal
    from app.services.session_log_service import (
        get_session_log_service, CLAUDE_PROJECTS_DIR,
    )

    service = get_session_log_service()
    db = SessionLocal()
    try:
        if args.session_id:
            matches = list(CLAUDE_PROJECTS_DIR.rglob(f"{args.session_id}.jsonl"))
            if not matches:
                print(f"transcript not found for session_id={args.session_id}", file=sys.stderr)
                return 1
            for path in matches:
                try:
                    r = service.ingest_from_jsonl(db, path, dry_run=args.dry_run)
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    r = {"status": "error", "message": repr(exc)}
                print(f"{path.name}: {r['status']} — {r['message']}")
            return 0

        # since-hours scan
        results = service.ingest_recent(db, since_hours=args.since_hours)
        if not results:
            print("대상 세션 transcript 없음", file=sys.stderr)
            return 1
        for r in results:
            print(f"{r.get('file', '?')}: {r['status']} — {r['message']}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
