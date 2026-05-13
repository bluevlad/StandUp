"""
Claude 세션 transcript 마스킹 룰

LLM 으로 전달하기 전 비밀번호 / API 키 / 토큰 / 개인정보 가능성을 마스킹.
보수적으로 false-positive 허용 (의심되면 마스킹).
"""

import re

# (이름, 패턴, 대체)
# 패턴은 단일 매칭 그룹 또는 전체 매치를 마스킹
RULES: list[tuple[str, re.Pattern, str]] = [
    # API keys / 토큰 — 명확한 prefix
    ("openai-key", re.compile(r"sk-[A-Za-z0-9\-_]{20,}"), "[MASKED:openai-key]"),
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}"), "[MASKED:anthropic-key]"),
    ("github-pat", re.compile(r"ghp_[A-Za-z0-9]{30,}"), "[MASKED:github-pat]"),
    ("github-oauth", re.compile(r"gho_[A-Za-z0-9]{30,}"), "[MASKED:github-oauth]"),
    ("github-app", re.compile(r"ghs_[A-Za-z0-9]{30,}"), "[MASKED:github-app]"),
    ("aws-key", re.compile(r"AKIA[0-9A-Z]{16}"), "[MASKED:aws-key]"),
    ("slack-token", re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}"), "[MASKED:slack-token]"),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "[MASKED:jwt]"),

    # key=value 형식 (라인 단위)
    (
        "kv-secret",
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?key|"
            r"private[_-]?key|auth[_-]?token|bearer)\s*[:=]\s*([\"']?)([^\s\"',;]{6,})\2"
        ),
        r"\1=[MASKED]",
    ),

    # 이메일 (선택적) — 마지막에 적용
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[MASKED:email]"),
]


def mask(text: str) -> str:
    if not text:
        return text
    for name, pat, repl in RULES:
        text = pat.sub(repl, text)
    return text


def mask_lines(lines: list[str]) -> list[str]:
    return [mask(line) for line in lines]
