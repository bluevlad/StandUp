"""Connector 베이스 추상 클래스."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from .schemas import FetchResult

logger = logging.getLogger(__name__)


class Connector(ABC):
    """외부 소스에서 데이터를 가져와 CanonicalEvent 리스트로 정규화."""

    name: str = "connector"
    enabled: bool = True

    @abstractmethod
    def fetch(self, since: datetime, until: datetime) -> FetchResult:
        """[since, until] 구간의 이벤트 수집."""

    def fetch_safe(self, since: datetime, until: datetime) -> FetchResult:
        """예외를 흡수해서 FetchResult 로 반환."""
        started = datetime.now(timezone.utc)
        try:
            return self.fetch(since, until)
        except Exception as e:  # noqa: BLE001 — 외부 소스 장애가 hub 전체를 죽이면 안 됨
            logger.error("connector %s 실패: %s", self.name, e, exc_info=True)
            finished = datetime.now(timezone.utc)
            return FetchResult(
                events=[], connector_name=self.name,
                started_at=started, finished_at=finished, error=str(e),
            )
