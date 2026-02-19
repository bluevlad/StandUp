"""
Auto-Tobe-Agent
Git Issues 조치사항 및 Commit 고도화 내용을 진행사항으로 정리 등록
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..core.database import SessionLocal
from ..services.github_service import get_github_service
from ..models.issue import WorkItem, ItemCategory, ItemStatus

logger = logging.getLogger(__name__)


class TobeAgent:
    """진행사항 추적 Agent"""

    def run(self):
        """Agent 실행 (스케줄러에서 호출)"""
        logger.info("=== Auto-Tobe-Agent 실행 시작 ===")

        github = get_github_service()
        if not github.is_configured:
            logger.warning("GitHub 토큰 미설정. Tobe-Agent 건너뜀.")
            return

        db = SessionLocal()
        try:
            repos = github.get_org_repos()
            since = datetime.now() - timedelta(hours=1)

            total_tracked = 0

            for repo in repos:
                tracked = self._track_progress(db, github, repo["name"], since)
                total_tracked += tracked

            logger.info(f"=== Tobe-Agent 완료: 추적 {total_tracked}건 ===")
        except Exception as e:
            logger.error(f"Tobe-Agent 오류: {e}", exc_info=True)
        finally:
            db.close()

    def _track_progress(
        self, db: Session, github, repo_name: str, since: datetime
    ) -> int:
        """커밋 기반 진행사항 추적"""
        commits = github.get_recent_commits(repo_name, since=since)
        tracked = 0

        for commit_data in commits:
            message = commit_data["message"].split("\n")[0]

            # 이미 등록된 커밋인지 확인
            existing = (
                db.query(WorkItem)
                .filter(
                    WorkItem.github_repo == repo_name,
                    WorkItem.related_commits.contains(commit_data["sha"]),
                )
                .first()
            )
            if existing:
                continue

            # Issue 참조 커밋인 경우 해당 WorkItem 업데이트
            issue_number = self._extract_issue_number(commit_data["message"])
            if issue_number:
                work_item = (
                    db.query(WorkItem)
                    .filter(
                        WorkItem.github_repo == repo_name,
                        WorkItem.github_issue_number == issue_number,
                    )
                    .first()
                )
                if work_item:
                    work_item.category = ItemCategory.IN_PROGRESS
                    work_item.status = ItemStatus.IN_PROGRESS
                    existing_commits = work_item.related_commits or ""
                    work_item.related_commits = (
                        f"{existing_commits},{commit_data['sha']}"
                        if existing_commits
                        else commit_data["sha"]
                    )
                    tracked += 1
                    continue

            # Issue 참조 없는 독립 커밋 → 진행사항으로 등록
            work_item = WorkItem(
                github_repo=repo_name,
                category=ItemCategory.IN_PROGRESS,
                status=ItemStatus.IN_PROGRESS,
                title=message[:500],
                summary=commit_data["message"][:1000],
                related_commits=commit_data["sha"],
            )
            db.add(work_item)
            tracked += 1

        db.commit()
        if tracked:
            logger.info(f"  [{repo_name}] 진행사항 추적: {tracked}건")

        return tracked

    def _extract_issue_number(self, commit_message: str) -> int | None:
        """커밋 메시지에서 Issue 번호 추출"""
        import re
        patterns = [
            r"#(\d+)",
            r"[Cc]loses?\s+#(\d+)",
            r"[Ff]ixes?\s+#(\d+)",
            r"[Rr]esolves?\s+#(\d+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, commit_message)
            if match:
                return int(match.group(1))
        return None


# 싱글톤
_agent = None


def get_tobe_agent() -> TobeAgent:
    global _agent
    if _agent is None:
        _agent = TobeAgent()
    return _agent
