"""
GitHub API 연동 서비스
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from github import Github, GithubException

from ..core.config import settings
from ..models.issue import ItemCategory

logger = logging.getLogger(__name__)


class GitHubService:
    """GitHub Issues/Commits 조회 서비스"""

    # Label → Category 매핑
    PLANNED_LABELS = {"enhancement", "feature", "refactor", "improvement", "planned"}
    REQUIRED_LABELS = {"bug", "request", "urgent", "hotfix", "required"}

    def __init__(self, token: str = None):
        self.token = token or settings.github_token
        self._client: Optional[Github] = None

    @property
    def client(self) -> Github:
        if self._client is None:
            if not self.token:
                raise ValueError("GITHUB_TOKEN이 설정되지 않았습니다.")
            self._client = Github(self.token)
        return self._client

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    def get_org_repos(self) -> list[dict]:
        """조직의 전체 저장소 목록 조회"""
        try:
            user = self.client.get_user(settings.github_org)
            repos = user.get_repos()
            return [
                {
                    "name": repo.name,
                    "full_name": repo.full_name,
                    "url": repo.html_url,
                    "updated_at": repo.updated_at,
                }
                for repo in repos
            ]
        except GithubException as e:
            logger.error(f"저장소 목록 조회 실패: {e}")
            return []

    def get_issues(self, repo_name: str, since: datetime = None, state: str = "all") -> list[dict]:
        """저장소의 Issues 조회"""
        try:
            repo = self.client.get_repo(f"{settings.github_org}/{repo_name}")
            kwargs = {"state": state, "sort": "updated", "direction": "desc"}
            if since:
                kwargs["since"] = since

            issues = repo.get_issues(**kwargs)
            result = []
            for issue in issues:
                if issue.pull_request:
                    continue

                labels = [label.name for label in issue.labels]
                category = self._classify_issue(labels)

                result.append({
                    "number": issue.number,
                    "title": issue.title,
                    "body": issue.body or "",
                    "state": issue.state,
                    "labels": labels,
                    "category": category,
                    "url": issue.html_url,
                    "created_at": issue.created_at,
                    "updated_at": issue.updated_at,
                    "closed_at": issue.closed_at,
                })

            return result

        except GithubException as e:
            logger.error(f"Issues 조회 실패 ({repo_name}): {e}")
            return []

    def get_recent_commits(self, repo_name: str, since: datetime = None) -> list[dict]:
        """저장소의 최근 커밋 조회"""
        try:
            repo = self.client.get_repo(f"{settings.github_org}/{repo_name}")
            kwargs = {}
            if since:
                kwargs["since"] = since

            commits = repo.get_commits(**kwargs)
            result = []
            for commit in commits[:50]:
                result.append({
                    "sha": commit.sha[:8],
                    "message": commit.commit.message,
                    "author": commit.commit.author.name if commit.commit.author else "unknown",
                    "date": commit.commit.author.date if commit.commit.author else None,
                    "url": commit.html_url,
                })

            return result

        except GithubException as e:
            logger.error(f"커밋 조회 실패 ({repo_name}): {e}")
            return []

    def _classify_issue(self, labels: list[str]) -> ItemCategory:
        """Issue Label 기반 분류"""
        label_set = {label.lower() for label in labels}

        if label_set & self.REQUIRED_LABELS:
            return ItemCategory.REQUIRED
        if label_set & self.PLANNED_LABELS:
            return ItemCategory.PLANNED

        return ItemCategory.PLANNED


# 싱글톤
_service: Optional[GitHubService] = None


def get_github_service() -> GitHubService:
    global _service
    if _service is None:
        _service = GitHubService()
    return _service
