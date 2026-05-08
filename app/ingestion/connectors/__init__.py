"""External-source connectors."""

from __future__ import annotations

from typing import Iterable

from ...core.config import settings
from ..base import Connector
from .loganalyzer import LogAnalyzerConnector
from .github_qa import GitHubQAConnector
from .auto_tobe import AutoTobeConnector
from .tech_trend import TechTrendConnector

__all__ = [
    "LogAnalyzerConnector", "GitHubQAConnector", "AutoTobeConnector",
    "TechTrendConnector",
    "build_connectors",
]


def build_connectors() -> list[Connector]:
    """env 설정에 따라 활성 connector 만 반환."""
    connectors: list[Connector] = []

    if settings.loganalyzer_enabled:
        connectors.append(LogAnalyzerConnector(
            base_url=settings.loganalyzer_base_url,
            window_days=settings.insight_window_days,
            excluded_services=settings.loganalyzer_excluded_services,
        ))

    if settings.github_qa_enabled and settings.github_token:
        connectors.append(GitHubQAConnector(
            token=settings.github_token,
            repos=settings.github_qa_repo_list,
            label=settings.github_qa_label,
        ))

    if settings.auto_tobe_enabled:
        connectors.append(AutoTobeConnector(
            journal_glob=settings.auto_tobe_journal_glob,
            git_repos=settings.auto_tobe_git_repo_list,
        ))

    if settings.tech_trend_enabled:
        connectors.append(TechTrendConnector(
            keywords=settings.tech_trend_keyword_list,
            reports_dir=settings.medium_digest_reports_dir,
        ))

    return connectors
