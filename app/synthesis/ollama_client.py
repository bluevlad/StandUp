"""
Ollama HTTP client wrapper.

/api/chat 사용 — system + user 메시지 분리, 결정적 출력 위해 temperature 낮춤.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from ..core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class GenResult:
    text: str
    model: str
    eval_count: int
    eval_duration_ms: int
    ok: bool
    error: Optional[str] = None


def chat(
    model: str,
    system: str,
    user: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout: Optional[int] = None,
) -> GenResult:
    """단발 채팅. 실패 시 ok=False 로 반환."""
    url = f"{settings.ollama_base_url}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    try:
        # trust_env=False — OrbStack 등 호스트 환경의 HTTPS_PROXY/HTTP_PROXY 가
        # Ollama 호출까지 가로채는 사고 방지. Ollama 는 보통 같은 호스트
        # (host.docker.internal:11434) 에 있어 프록시를 거치면 안 된다.
        with httpx.Client(
            timeout=timeout or settings.ollama_timeout_sec,
            trust_env=False,
        ) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
        text = (data.get("message") or {}).get("content", "").strip()
        return GenResult(
            text=text,
            model=model,
            eval_count=data.get("eval_count", 0),
            eval_duration_ms=int(data.get("eval_duration", 0) / 1_000_000),
            ok=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("ollama chat 실패 model=%s err=%s", model, e)
        return GenResult(text="", model=model, eval_count=0, eval_duration_ms=0,
                         ok=False, error=str(e))
