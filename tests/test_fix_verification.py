"""fix 효과 검증 — 순수 판정 로직 + fingerprint 파싱 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.ingestion.connectors.auto_tobe import AutoTobeConnector
from app.services.fix_verification_service import (
    STATUS_PENDING, STATUS_RECURRED, STATUS_VERIFIED,
    FixVerification, extract_fingerprints, format_verification_block,
    resolve_status,
)

_FIX_AT = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)


def _dt(days: float) -> datetime:
    return _FIX_AT + timedelta(days=days)


# ── resolve_status ───────────────────────────────────────────────────────

def test_recurrence_within_window_is_recurred():
    status, recurred_at, count = resolve_status(
        _FIX_AT, [_dt(2), _dt(5)], now=_dt(10), window_days=7,
    )
    assert status == STATUS_RECURRED
    assert recurred_at == _dt(2)
    assert count == 2


def test_no_recurrence_after_window_is_verified():
    status, recurred_at, count = resolve_status(
        _FIX_AT, [], now=_dt(8), window_days=7,
    )
    assert status == STATUS_VERIFIED
    assert recurred_at is None
    assert count == 0


def test_no_recurrence_before_window_end_is_pending():
    status, _, _ = resolve_status(_FIX_AT, [], now=_dt(3), window_days=7)
    assert status == STATUS_PENDING


def test_recurrence_after_window_does_not_count():
    """window 밖(8일째) 재발은 계약상 검증 성공."""
    status, _, count = resolve_status(
        _FIX_AT, [_dt(8)], now=_dt(9), window_days=7,
    )
    assert status == STATUS_VERIFIED
    assert count == 0


def test_recurrence_at_exact_fix_time_ignored():
    """fix 시점과 동일한 occurred_at(수집 잔상)은 재발로 치지 않음."""
    status, _, _ = resolve_status(_FIX_AT, [_FIX_AT], now=_dt(8), window_days=7)
    assert status == STATUS_VERIFIED


# ── extract_fingerprints ─────────────────────────────────────────────────

def test_extract_single_signature():
    assert extract_fingerprints(
        {"before_log_signature": "534c11c4240a341e"}
    ) == ["534c11c4240a341e"]


def test_extract_signature_list_dedup():
    fps = extract_fingerprints({
        "before_log_signatures": ["aaa11111", "bbb22222"],
        "before_log_signature": "aaa11111",
    })
    assert fps == ["aaa11111", "bbb22222"]


def test_extract_none_and_missing():
    assert extract_fingerprints({"before_log_signature": None}) == []
    assert extract_fingerprints({}) == []
    assert extract_fingerprints(None) == []


# ── connector 파싱 ───────────────────────────────────────────────────────

def test_journal_signature_regex():
    content = (
        "## 2026-08-10 fix-allergy-1a2b3c4d\n\n"
        "```yaml\n"
        "target_service: allergy\n"
        'before_log_signature: "534c11c4240a341e"\n'
        "```\n"
    )
    found = AutoTobeConnector._BEFORE_SIG_RE.findall(content)
    assert found == ["534c11c4240a341e"]


def test_commit_footer_signature_regex():
    body = (
        "- None 체크 추가\n\n"
        "Root-Cause: null-handling\n"
        "Before-Log-Signature: 9d3837dc212e6c26\n"
        "Affected-Layer: backend/api\n"
    )
    m = AutoTobeConnector._COMMIT_SIG_RE.search(body)
    assert m and m.group(1) == "9d3837dc212e6c26"


def test_commit_footer_absent_returns_none():
    assert AutoTobeConnector._COMMIT_SIG_RE.search("Root-Cause: x\n") is None


# ── format_verification_block ────────────────────────────────────────────

def test_format_block_empty():
    assert format_verification_block([]) == "(효과 검증 데이터 없음)"


def test_format_block_states():
    vs = [
        FixVerification(
            fix_event_id="e1", fix_title="fix(api): None 처리",
            fix_source_type="auto_tobe_commit", fixed_at=_FIX_AT,
            fingerprint="534c11c4240a341e", status=STATUS_VERIFIED,
            window_days=7,
        ),
        FixVerification(
            fix_event_id="e2", fix_title="fix(gw): proxy 재시도",
            fix_source_type="auto_tobe_commit", fixed_at=_FIX_AT,
            fingerprint="9d3837dc212e6c26", status=STATUS_RECURRED,
            window_days=7, recurred_at=_dt(2), recurrence_count=3,
        ),
    ]
    block = format_verification_block(vs)
    assert "✅ 검증됨" in block
    assert "❌ 재발" in block
    assert "재발 3회 (최초 2026-08-12)" in block
    assert "534c11c4240a341e" in block
