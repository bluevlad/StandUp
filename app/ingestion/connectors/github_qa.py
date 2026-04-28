"""
GitHub QA-Agent connector.

QA Agent (외부 PC)가 GitHub Issues 에 라벨 'qa-agent' 로 등록한 결과를 수집.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ...models.insight import COLLECTION_QA, SOURCE_GITHUB_QA
from ..base import Connector
from ..schemas import CanonicalEvent, ChunkSpec, FetchResult

logger = logging.getLogger(__name__)


class GitHubQAConnector(Connector):
    name = "github_qa"

    def __init__(self, token: str, repos: list[str], label: str = "qa-agent"):
        self.token = token
        self.repos = repos
        self.label = label

    def fetch(self, since: datetime, until: datetime) -> FetchResult:
        started = datetime.now(timezone.utc)
        events: list[CanonicalEvent] = []

        if not self.repos:
            logger.info("github_qa: repo 목록 비어있음 — skip")
            return FetchResult(
                events=events, connector_name=self.name,
                started_at=started, finished_at=datetime.now(timezone.utc),
            )

        try:
            from github import Github
        except ImportError:
            logger.warning("PyGithub 미설치 — github_qa skip")
            return FetchResult(
                events=events, connector_name=self.name,
                started_at=started, finished_at=datetime.now(timezone.utc),
                error="PyGithub not installed",
            )

        gh = Github(self.token)
        for full_name in self.repos:
            try:
                repo = gh.get_repo(full_name)
                # 라벨 + since 필터로 가져옴
                issues = repo.get_issues(
                    state="all", labels=[self.label], since=since,
                )
                for issue in issues:
                    if issue.created_at and issue.created_at < since:
                        # since 이전 created 도 since 이후 update 면 잡힘 — 본문 갱신 위주는 OK
                        pass

                    body = issue.body or ""
                    excerpt = body[:240] + ("…" if len(body) > 240 else "")
                    labels = [l.name for l in issue.labels]
                    severity = self._severity_from_labels(labels)

                    events.append(CanonicalEvent(
                        source_type=SOURCE_GITHUB_QA,
                        source_id=f"{full_name}#{issue.number}",
                        occurred_at=issue.updated_at or issue.created_at,
                        title=issue.title,
                        source_url=issue.html_url,
                        service_tag=self._service_from_labels(labels),
                        severity=severity,
                        category="qa_issue",
                        canonical={
                            "repo": full_name,
                            "number": issue.number,
                            "state": issue.state,
                            "labels": labels,
                            "body_md": body,
                            "comments": issue.comments,
                            "created_at": issue.created_at.isoformat() if issue.created_at else None,
                            "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
                        },
                        raw_excerpt=excerpt,
                        extra_chunks=[
                            ChunkSpec(
                                text=f"[QA] {issue.title}\n{body}",
                                collection=COLLECTION_QA,
                                metadata={"repo": full_name, "issue": issue.number,
                                          "labels": labels},
                            ),
                        ],
                    ))
            except Exception as e:  # noqa: BLE001
                logger.warning("github_qa repo=%s 실패: %s", full_name, e)

        return FetchResult(
            events=events, connector_name=self.name,
            started_at=started, finished_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _severity_from_labels(labels: list[str]) -> str | None:
        for label in labels:
            ll = label.lower()
            for sev in ("critical", "high", "medium", "low"):
                if ll == f"severity:{sev}" or ll == sev:
                    return sev
        return None

    @staticmethod
    def _service_from_labels(labels: list[str]) -> str | None:
        for label in labels:
            if label.lower().startswith("service:"):
                return label.split(":", 1)[1].strip()
        return None
