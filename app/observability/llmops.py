"""LLMOps batch_runs 보고용 클라이언트.

표준: standards/observability/BATCH_RUN_REPORTING.md
- POST {LLMOPS_URL}/api/batch-runs (X-LLMOps-Key + X-Consumer-Id)
- fire-and-forget: 타임아웃 ≤ 1s, 예외 swallow, 백그라운드 스레드
- 재시도 금지 (관측 데이터 누락 허용)

의존성: 표준 라이브러리만 (urllib). httpx 있으면 자동 사용.

사용 예 (단순):
    from llmops import report_batch_run

    report_batch_run(
        consumer_id="standup-weekly-newsletter",
        run_id=f"{datetime.utcnow().isoformat()}-{os.getpid()}",
        started_at=started_at,
        ended_at=datetime.utcnow(),
        status="success",
        stages=[
            {"name": "summarization", "model": "llama3.2:3b",
             "tokens_in": 1024, "tokens_out": 180, "duration_ms": 31200},
        ],
        metrics={"items_processed": 12},
    )

사용 예 (재사용 클라이언트):
    client = LLMOpsClient(consumer_id="standup-weekly-newsletter")
    client.report(run_id="...", started_at=..., status="success", stages=[...])

설정 (환경변수):
    LLMOPS_URL=https://llmops.unmong.com/api/batch-runs   (또는 http://host.docker.internal:9110/api/batch-runs)
    LLMOPS_API_KEY=<consumer 별 발급된 키>
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Iterable

__all__ = ["LLMOpsClient", "StageReport", "flush_pending", "report_batch_run"]

logger = logging.getLogger(__name__)

DEFAULT_URL = os.environ.get(
    "LLMOPS_URL", "http://host.docker.internal:9110/api/batch-runs"
)
DEFAULT_TIMEOUT = 1.0  # 표준: ≤ 1초

# pending fire-and-forget threads 추적 — 짧게 끝나는 process 에서 flush() 로 join 가능.
_PENDING_THREADS: set[threading.Thread] = set()
_PENDING_LOCK = threading.Lock()


@dataclass
class StageReport:
    """단계별 LLM 호출 보고. cascade 한 단계 = 1 stage."""
    name: str | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    duration_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class _Payload:
    consumer_id: str
    run_id: str
    started_at: str
    status: str
    ended_at: str | None = None
    stages: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    extra: dict[str, Any] | None = None

    def to_json(self) -> bytes:
        d = asdict(self)
        d = {k: v for k, v in d.items() if v is not None}
        return json.dumps(d, default=str).encode("utf-8")


def _iso(dt: datetime | str) -> str:
    return dt.isoformat() if isinstance(dt, datetime) else dt


def _send(
    url: str,
    api_key: str,
    consumer_id: str,
    payload: bytes,
    timeout: float,
) -> None:
    """단일 전송. 절대 예외 throw 안 함. 종료 시 자기 자신을 _PENDING_THREADS 에서 제거."""
    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-LLMOps-Key": api_key,
                "X-Consumer-Id": consumer_id,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as res:
            res.read()
    except urllib.error.HTTPError as e:
        # 4xx/5xx — 재시도 없이 로깅만
        logger.debug("LLMOps HTTP %s: %s", e.code, e.reason)
    except Exception as e:  # noqa: BLE001 — fire-and-forget 원칙
        logger.debug("LLMOps send swallowed: %s", e)
    finally:
        with _PENDING_LOCK:
            _PENDING_THREADS.discard(threading.current_thread())


def flush_pending(timeout: float = 2.0) -> int:
    """진행 중인 fire-and-forget threads 가 끝날 때까지 wait.

    짧은 lifetime 의 process (배치 잡 등) 종료 직전 호출. 정기 cron 으로 상주
    프로세스 안에서 도는 잡은 호출 불필요 (daemon thread 가 자연스럽게 완료).

    Returns: 시간 내 완료된 thread 수.
    """
    with _PENDING_LOCK:
        pending = list(_PENDING_THREADS)
    if not pending:
        return 0
    deadline = None
    if timeout > 0:
        import time as _time
        deadline = _time.monotonic() + timeout
    done = 0
    for t in pending:
        remain = None if deadline is None else max(0.0, deadline - _time.monotonic())
        t.join(timeout=remain)
        if not t.is_alive():
            done += 1
    return done


class LLMOpsClient:
    """consumer_id 가 고정된 재사용 가능한 클라이언트.

    .report(...) 호출 시 즉시 daemon 스레드로 전송 후 반환.
    """

    def __init__(
        self,
        consumer_id: str,
        *,
        url: str | None = None,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        enabled: bool = True,
    ) -> None:
        self.consumer_id = consumer_id
        self.url = url or DEFAULT_URL
        self.api_key = api_key or os.environ.get("LLMOPS_API_KEY", "")
        self.timeout = timeout
        self.enabled = enabled and bool(self.api_key)
        if not self.enabled:
            logger.debug(
                "LLMOpsClient(%s) disabled (no LLMOPS_API_KEY)", consumer_id
            )

    def report(
        self,
        *,
        run_id: str,
        started_at: datetime | str,
        status: str,
        ended_at: datetime | str | None = None,
        stages: Iterable[StageReport | dict[str, Any]] = (),
        metrics: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return

        stage_dicts = [
            s.to_dict() if isinstance(s, StageReport) else dict(s) for s in stages
        ]
        payload = _Payload(
            consumer_id=self.consumer_id,
            run_id=run_id,
            started_at=_iso(started_at),
            ended_at=_iso(ended_at) if ended_at else None,
            status=status,
            stages=stage_dicts,
            metrics=metrics,
            error=error,
            extra=extra,
        ).to_json()

        t = threading.Thread(
            target=_send,
            args=(self.url, self.api_key, self.consumer_id, payload, self.timeout),
            daemon=True,
        )
        with _PENDING_LOCK:
            _PENDING_THREADS.add(t)
        t.start()

    @staticmethod
    def flush(timeout: float = 2.0) -> int:
        """편의용 — 모듈 함수 flush_pending() 과 동일."""
        return flush_pending(timeout)


def report_batch_run(
    *,
    consumer_id: str,
    run_id: str,
    started_at: datetime | str,
    status: str,
    ended_at: datetime | str | None = None,
    stages: Iterable[StageReport | dict[str, Any]] = (),
    metrics: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    url: str | None = None,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> None:
    """1회성 보고 — 모듈 함수 형태. 내부에서 LLMOpsClient 1회 생성 후 호출."""
    LLMOpsClient(
        consumer_id=consumer_id,
        url=url,
        api_key=api_key,
        timeout=timeout,
    ).report(
        run_id=run_id,
        started_at=started_at,
        ended_at=ended_at,
        status=status,
        stages=stages,
        metrics=metrics,
        error=error,
        extra=extra,
    )
