"""
Autonomous-QA-Agent
주기적으로 GitHub Issues를 검수하여 예정사항/요구사항으로 분류 등록
"""

import time
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..core.database import SessionLocal
from ..services.github_service import get_github_service
from ..models.issue import WorkItem, ItemCategory, ItemStatus
from ..models.agent_log import AgentLog

logger = logging.getLogger(__name__)


class QAAgent:
    """GitHub Issues 자동 검수 Agent"""

    INITIAL_SCAN_DAYS = 30
    REGULAR_SCAN_HOURS = 2

    def run(self):
        """Agent 실행 (스케줄러에서 호출)"""
        logger.info("=== Autonomous-QA-Agent 실행 시작 ===")
        start_time = time.time()

        github = get_github_service()
        if not github.is_configured:
            logger.warning("GitHub 토큰 미설정. QA-Agent 건너뜀.")
            return

        db = SessionLocal()
        try:
            existing_count = db.query(WorkItem).count()
            if existing_count == 0:
                since = datetime.now() - timedelta(days=self.INITIAL_SCAN_DAYS)
                logger.info(f"초기 스캔 모드: 최근 {self.INITIAL_SCAN_DAYS}일")
            else:
                since = datetime.now() - timedelta(hours=self.REGULAR_SCAN_HOURS)
                logger.info(f"정기 스캔 모드: 최근 {self.REGULAR_SCAN_HOURS}시간")

            repos = github.get_org_repos()
            total_new = 0
            total_updated = 0

            for repo in repos:
                new, updated = self._scan_repo(db, github, repo["name"], since)
                total_new += new
                total_updated += updated

            duration = time.time() - start_time
            logger.info(
                f"=== QA-Agent 완료: 신규 {total_new}건, 갱신 {total_updated}건 "
                f"({duration:.1f}초) ==="
            )

            # 실행 이력 기록
            log = AgentLog(
                agent_name="QA-Agent",
                action="issues_scan",
                status="success",
                detail=f"신규 {total_new}건, 갱신 {total_updated}건",
                items_processed=total_new + total_updated,
                duration_seconds=round(duration, 2),
            )
            db.add(log)
            db.commit()

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"QA-Agent 오류: {e}", exc_info=True)
            try:
                log = AgentLog(
                    agent_name="QA-Agent",
                    action="issues_scan",
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

    def _scan_repo(
        self, db: Session, github, repo_name: str, since: datetime
    ) -> tuple[int, int]:
        """저장소 Issues 스캔"""
        issues = github.get_issues(repo_name, since=since)
        new_count = 0
        updated_count = 0

        for issue_data in issues:
            existing = (
                db.query(WorkItem)
                .filter(
                    WorkItem.github_repo == repo_name,
                    WorkItem.github_issue_number == issue_data["number"],
                )
                .first()
            )

            if existing:
                existing.title = issue_data["title"]
                existing.summary = issue_data["body"][:1000] if issue_data["body"] else None
                existing.labels = ",".join(issue_data["labels"])
                existing.category = issue_data["category"]
                if issue_data["state"] == "closed" and existing.status != ItemStatus.CLOSED:
                    existing.status = ItemStatus.CLOSED
                    existing.resolved_at = issue_data["closed_at"]
                updated_count += 1
            else:
                status = (
                    ItemStatus.CLOSED if issue_data["state"] == "closed"
                    else ItemStatus.OPEN
                )
                work_item = WorkItem(
                    github_repo=repo_name,
                    github_issue_number=issue_data["number"],
                    github_issue_url=issue_data["url"],
                    category=issue_data["category"],
                    status=status,
                    title=issue_data["title"],
                    summary=issue_data["body"][:1000] if issue_data["body"] else None,
                    labels=",".join(issue_data["labels"]),
                )
                if issue_data["state"] == "closed":
                    work_item.resolved_at = issue_data["closed_at"]
                db.add(work_item)
                new_count += 1

        db.commit()
        if new_count or updated_count:
            logger.info(f"  [{repo_name}] 신규: {new_count}, 갱신: {updated_count}")

        return new_count, updated_count


# 싱글톤
_agent = None


def get_qa_agent() -> QAAgent:
    global _agent
    if _agent is None:
        _agent = QAAgent()
    return _agent
