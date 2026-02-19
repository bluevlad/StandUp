"""
Auto-Tobe-Agent
Git Issues 조치사항 및 Commit 고도화 내용을 진행사항으로 정리 등록
"""

import re
import time
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..core.database import SessionLocal
from ..services.github_service import get_github_service, create_github_service_from_provider
from ..services import config_service
from ..models.issue import WorkItem, ItemCategory, ItemStatus
from ..models.agent_log import AgentLog

logger = logging.getLogger(__name__)

# Issue 번호 추출 패턴
_ISSUE_PATTERNS = [
    re.compile(r"#(\d+)"),
    re.compile(r"[Cc]loses?\s+#(\d+)"),
    re.compile(r"[Ff]ixes?\s+#(\d+)"),
    re.compile(r"[Rr]esolves?\s+#(\d+)"),
]


class TobeAgent:
    """진행사항 추적 Agent"""

    INITIAL_SCAN_DAYS = 14
    REGULAR_SCAN_HOURS = 1

    def run(self):
        """Agent 실행 (스케줄러에서 호출)"""
        logger.info("=== Auto-Tobe-Agent 실행 시작 ===")
        start_time = time.time()

        db = SessionLocal()
        try:
            commit_items = db.query(WorkItem).filter(
                WorkItem.related_commits.isnot(None)
            ).count()
            if commit_items == 0:
                since = datetime.now() - timedelta(days=self.INITIAL_SCAN_DAYS)
                logger.info(f"초기 스캔 모드: 최근 {self.INITIAL_SCAN_DAYS}일")
            else:
                since = datetime.now() - timedelta(hours=self.REGULAR_SCAN_HOURS)
                logger.info(f"정기 스캔 모드: 최근 {self.REGULAR_SCAN_HOURS}시간")

            total_tracked = 0

            # DB에 git_providers가 있으면 등록된 리포만 스캔
            providers = config_service.get_active_git_providers(db)
            if providers:
                for provider in providers:
                    github = create_github_service_from_provider(provider)
                    if not github.is_configured:
                        continue
                    repos = config_service.get_active_repositories(db, provider.id)
                    if repos:
                        for repo in repos:
                            tracked = self._track_progress(db, github, repo.repo_name, since)
                            total_tracked += tracked
                    else:
                        org_repos = github.get_org_repos()
                        for repo in org_repos:
                            tracked = self._track_progress(db, github, repo["name"], since)
                            total_tracked += tracked
            else:
                # .env fallback: 기존 방식
                github = get_github_service()
                if not github.is_configured:
                    logger.warning("GitHub 토큰 미설정. Tobe-Agent 건너뜀.")
                    return

                repos = github.get_org_repos()
                for repo in repos:
                    tracked = self._track_progress(db, github, repo["name"], since)
                    total_tracked += tracked

            duration = time.time() - start_time
            logger.info(
                f"=== Tobe-Agent 완료: 추적 {total_tracked}건 ({duration:.1f}초) ==="
            )

            log = AgentLog(
                agent_name="Tobe-Agent",
                action="commit_track",
                status="success",
                detail=f"추적 {total_tracked}건",
                items_processed=total_tracked,
                duration_seconds=round(duration, 2),
            )
            db.add(log)
            db.commit()

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Tobe-Agent 오류: {e}", exc_info=True)
            try:
                log = AgentLog(
                    agent_name="Tobe-Agent",
                    action="commit_track",
                    status="error",
                    detail=str(e)[:1000],
                    duration_seconds=round(duration, 2),
                )
                db.add(log)
                db.commit()
            except Exception:
                pass
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

    @staticmethod
    def _extract_issue_number(commit_message: str) -> int | None:
        """커밋 메시지에서 Issue 번호 추출"""
        for pattern in _ISSUE_PATTERNS:
            match = pattern.search(commit_message)
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
