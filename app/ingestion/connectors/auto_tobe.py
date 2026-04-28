"""
Auto-Tobe-Agent connector.

두 가지 채널:
1. journal — auto_tobe_journal_glob 로 매칭되는 Markdown 파일 변경분
2. git commit — auto_tobe_git_repos 의 'Root-Cause:' footer 가진 fix 커밋
"""

from __future__ import annotations

import glob
import hashlib
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ...models.insight import COLLECTION_FIXES, SOURCE_AUTO_TOBE_COMMIT, SOURCE_AUTO_TOBE_JOURNAL
from ..base import Connector
from ..schemas import CanonicalEvent, ChunkSpec, FetchResult

logger = logging.getLogger(__name__)


class AutoTobeConnector(Connector):
    name = "auto_tobe"

    def __init__(self, journal_glob: str, git_repos: list[str]):
        self.journal_glob = journal_glob
        self.git_repos = git_repos

    def fetch(self, since: datetime, until: datetime) -> FetchResult:
        started = datetime.now(timezone.utc)
        events: list[CanonicalEvent] = []

        if self.journal_glob:
            events.extend(self._fetch_journals(since, until))

        for repo_path in self.git_repos:
            try:
                events.extend(self._fetch_git_commits(repo_path, since, until))
            except Exception as e:  # noqa: BLE001
                logger.warning("auto_tobe git repo=%s 실패: %s", repo_path, e)

        return FetchResult(
            events=events, connector_name=self.name,
            started_at=started, finished_at=datetime.now(timezone.utc),
        )

    # ── journal 파일 ─────────────────────────────────────────────────────
    def _fetch_journals(self, since: datetime, until: datetime) -> list[CanonicalEvent]:
        out: list[CanonicalEvent] = []
        for path_str in glob.glob(self.journal_glob):
            p = Path(path_str)
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if mtime < since or mtime > until:
                continue
            try:
                content = p.read_text(encoding="utf-8")
            except Exception as e:  # noqa: BLE001
                logger.warning("journal 읽기 실패 %s: %s", p, e)
                continue

            digest = hashlib.sha256(content.encode()).hexdigest()[:16]
            excerpt = content[:240] + ("…" if len(content) > 240 else "")
            out.append(CanonicalEvent(
                source_type=SOURCE_AUTO_TOBE_JOURNAL,
                source_id=f"{p.name}#{digest}",
                occurred_at=mtime,
                title=f"Auto-Tobe journal: {p.name}",
                source_url=f"file://{p}",
                category="fix_journal",
                severity="info",
                canonical={"path": str(p), "size": len(content)},
                raw_excerpt=excerpt,
                extra_chunks=[
                    ChunkSpec(
                        text=content[:8000],
                        collection=COLLECTION_FIXES,
                        metadata={"file": p.name, "type": "journal"},
                    ),
                ],
            ))
        return out

    # ── git commits with Root-Cause footer ───────────────────────────────
    _ROOT_CAUSE_RE = re.compile(r"^Root-Cause:\s*(\S+)", re.MULTILINE)
    _LAYER_RE = re.compile(r"^Affected-Layer:\s*(\S+)", re.MULTILINE)

    def _fetch_git_commits(self, repo_path: str, since: datetime, until: datetime) -> list[CanonicalEvent]:
        out: list[CanonicalEvent] = []
        repo = Path(repo_path)
        if not (repo / ".git").exists():
            logger.warning("auto_tobe: %s 는 git repo 아님", repo)
            return out

        # since 이후 fix 커밋만 (Root-Cause: 포함된 것만 후처리 필터)
        since_iso = since.isoformat()
        until_iso = until.isoformat()
        try:
            log_out = subprocess.check_output(
                [
                    "git", "-C", str(repo), "log",
                    f"--since={since_iso}", f"--until={until_iso}",
                    "--grep=Root-Cause:", "-i",
                    "--pretty=format:%H%x1f%aI%x1f%s%x1f%b%x1e",
                ],
                text=True, encoding="utf-8", errors="replace", timeout=30,
            )
        except subprocess.SubprocessError as e:
            logger.warning("git log 실패 %s: %s", repo, e)
            return out

        for record in log_out.split("\x1e"):
            record = record.strip()
            if not record:
                continue
            parts = record.split("\x1f")
            if len(parts) < 4:
                continue
            sha, iso, subject, body = parts[0], parts[1], parts[2], parts[3]
            try:
                occurred = datetime.fromisoformat(iso)
            except ValueError:
                continue

            rc_match = self._ROOT_CAUSE_RE.search(body)
            layer_match = self._LAYER_RE.search(body)
            root_cause = rc_match.group(1) if rc_match else None
            layer = layer_match.group(1) if layer_match else None

            excerpt = (subject + "\n" + body)[:240]
            chunk_text = f"[FIX] {subject}\n\n{body}\n\n(repo={repo.name} sha={sha[:8]})"

            out.append(CanonicalEvent(
                source_type=SOURCE_AUTO_TOBE_COMMIT,
                source_id=f"{repo.name}@{sha}",
                occurred_at=occurred,
                title=subject,
                source_url=f"file://{repo}/.git/{sha}",
                service_tag=repo.name,
                severity="info",
                category="fix_commit",
                canonical={
                    "repo": repo.name,
                    "sha": sha,
                    "root_cause": root_cause,
                    "affected_layer": layer,
                    "subject": subject,
                    "body": body,
                },
                raw_excerpt=excerpt,
                extra_chunks=[
                    ChunkSpec(
                        text=chunk_text,
                        collection=COLLECTION_FIXES,
                        metadata={
                            "repo": repo.name, "sha": sha,
                            "root_cause": root_cause, "layer": layer,
                        },
                    ),
                ],
            ))
        return out
