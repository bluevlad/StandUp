"""
GitHub API 연결 테스트 스크립트
Usage: python -m scripts.test_github
"""

import sys
import os
import logging
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    from app.services.github_service import GitHubService
    from app.core.config import settings

    logger.info("=== GitHub API 연결 테스트 ===")
    logger.info(f"Organization: {settings.github_org}")
    logger.info(f"Token 설정: {'OK' if settings.github_token else 'MISSING'}")

    service = GitHubService()

    if not service.is_configured:
        logger.error("GITHUB_TOKEN이 설정되지 않았습니다.")
        sys.exit(1)

    # 1. 저장소 목록 조회
    logger.info("\n--- 저장소 목록 ---")
    repos = service.get_org_repos()
    logger.info(f"총 {len(repos)}개 저장소 발견")
    for repo in repos:
        logger.info(f"  - {repo['name']} (updated: {repo['updated_at']})")

    if not repos:
        logger.warning("저장소가 없습니다.")
        return

    # 2. 각 저장소 Issues 조회 (최근 30일)
    since = datetime.now() - timedelta(days=30)
    logger.info(f"\n--- Issues 조회 (since: {since.strftime('%Y-%m-%d')}) ---")

    total_issues = 0
    for repo in repos[:10]:
        issues = service.get_issues(repo["name"], since=since)
        if issues:
            logger.info(f"\n  [{repo['name']}] {len(issues)}건")
            for issue in issues[:5]:
                labels_str = ", ".join(issue["labels"]) if issue["labels"] else "no labels"
                logger.info(
                    f"    #{issue['number']} [{issue['category'].value}] "
                    f"{issue['title'][:60]} ({labels_str})"
                )
            total_issues += len(issues)

    logger.info(f"\n총 Issues: {total_issues}건")

    # 3. 각 저장소 최근 커밋 조회 (최근 7일)
    since_commits = datetime.now() - timedelta(days=7)
    logger.info(f"\n--- 최근 커밋 조회 (since: {since_commits.strftime('%Y-%m-%d')}) ---")

    total_commits = 0
    for repo in repos[:10]:
        commits = service.get_recent_commits(repo["name"], since=since_commits)
        if commits:
            logger.info(f"\n  [{repo['name']}] {len(commits)}건")
            for commit in commits[:3]:
                msg = commit["message"].split("\n")[0][:60]
                logger.info(f"    {commit['sha']} {msg}")
            total_commits += len(commits)

    logger.info(f"\n총 Commits: {total_commits}건")
    logger.info("\n=== GitHub API 테스트 완료 ===")


if __name__ == "__main__":
    main()
