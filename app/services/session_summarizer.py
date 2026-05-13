"""
Claude 세션 transcript → LLM 요약 (Ollama qwen2.5:7b 기본).
실패 시 None 반환 → 호출자가 rule-based fallback 으로 대체.
"""

import json
import logging
import re
from typing import Optional

from ..core.config import settings
from ..synthesis.ollama_client import chat
from .session_masker import mask

logger = logging.getLogger(__name__)

MAX_INPUT_CHARS = 12000  # qwen2.5:7b context 안전 영역
MAX_USER_MSG_PER_SESSION = 8
MAX_TOOL_NAMES = 30

SYSTEM_PROMPT = (
    "당신은 개발 세션 회의록 정리 비서입니다. "
    "사용자가 전달한 Claude Code 세션 정보를 회의록 양식으로 요약하세요. "
    "반드시 아래 JSON 스키마로만 응답하고, 다른 텍스트는 출력하지 마세요.\n\n"
    "{\n"
    '  "topic": "한 줄 주제 및 안건 (80자 이내)",\n'
    '  "items": [\n'
    '    {"title": "회의 내용 항목 제목", "content": "1-2문장 상세"}\n'
    "  ],\n"
    '  "pending": ["미결사항 또는 후속 TODO 단문"]\n'
    "}\n\n"
    "규칙:\n"
    "- items 는 실제 진행된 작업 단위로 3~7개 사이.\n"
    "- pending 은 명확한 후속 작업만. 없으면 빈 배열.\n"
    "- 한국어로 작성.\n"
    "- 마스킹된 [MASKED:*] 토큰은 그대로 두세요.\n"
)


def _compact_transcript(parsed: dict, commits: list[dict], user_messages: list[str]) -> str:
    """LLM 입력용 압축 텍스트 생성 (마스킹 후)"""
    lines: list[str] = []
    lines.append(f"# 프로젝트: {parsed.get('cwd', '?')}")
    lines.append(f"# 브랜치: {parsed.get('git_branch', '?')}")
    lines.append(f"# 시작-종료: {parsed['started_at']} ~ {parsed['ended_at']}")
    lines.append(f"# 메시지: user={parsed['user_msg_count']}, assistant={parsed['assistant_msg_count']}, tool_use={parsed['tool_use_count']}")
    lines.append("")

    lines.append("## 사용자 요청 (요약, 상위 N건)")
    for i, msg in enumerate(user_messages[:MAX_USER_MSG_PER_SESSION], start=1):
        snippet = mask(msg).strip().replace("\n", " ")[:400]
        lines.append(f"{i}. {snippet}")
    lines.append("")

    if commits:
        lines.append("## 커밋 (실제 변경)")
        for c in commits[:30]:
            msg = mask((c.get("message") or "").split("\n", 1)[0])[:200]
            lines.append(f"- {c['sha'][:8]} {msg}")
        lines.append("")

    text = "\n".join(lines)
    if len(text) > MAX_INPUT_CHARS:
        text = text[:MAX_INPUT_CHARS] + "\n... (truncated)"
    return text


_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    # 1) 그대로 파싱
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2) 첫 번째 { ... } 블록 추출
    m = _JSON_BLOCK.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def summarize_session(
    parsed: dict,
    commits: list[dict],
    user_messages: list[str],
) -> Optional[dict]:
    """
    반환: {"topic": str, "items": [{"title","content"}], "pending": [str]}  또는 None
    """
    if not settings.session_log_llm_enabled:
        return None

    user_prompt = _compact_transcript(parsed, commits, user_messages)
    model = settings.session_log_summary_model or settings.ollama_model_summarize

    result = chat(
        model=model,
        system=SYSTEM_PROMPT,
        user=user_prompt,
        temperature=0.2,
        max_tokens=1500,
        timeout=settings.session_log_llm_timeout_sec,
    )
    if not result.ok:
        logger.warning("session LLM 요약 실패 model=%s err=%s", model, result.error)
        return None

    parsed_out = _extract_json(result.text)
    if not parsed_out:
        logger.warning("session LLM JSON 파싱 실패: %s", (result.text or "")[:200])
        return None

    topic = (parsed_out.get("topic") or "").strip()
    raw_items = parsed_out.get("items") or []
    raw_pending = parsed_out.get("pending") or []

    items: list[dict] = []
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        title = (it.get("title") or "").strip()
        if not title:
            continue
        items.append({
            "title": title[:480],
            "content": (it.get("content") or "").strip()[:2000],
        })

    pending: list[str] = []
    for p in raw_pending:
        if isinstance(p, str) and p.strip():
            pending.append(p.strip()[:480])

    if not topic and not items:
        return None
    return {
        "topic": topic[:480] if topic else "",
        "items": items,
        "pending": pending,
    }
