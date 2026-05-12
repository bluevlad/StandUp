"""
Newsletter sender — recipients 테이블에서 report_types LIKE '%insight%' 만 추림.
기존 EmailService 재활용.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.database import SessionLocal
from ..models.insight import Newsletter
from ..models.recipient import Recipient
from ..services.email_service import get_email_service, SendResult

logger = logging.getLogger(__name__)


@dataclass
class SendSummary:
    total: int
    success: int
    failed: int
    failures: list[tuple[str, str]]


def list_insight_recipients(session: Session) -> list[str]:
    rows = session.execute(
        select(Recipient.email)
        .where(Recipient.is_active.is_(True))
        .where(
            (Recipient.report_types == "all")
            | Recipient.report_types.like("%insight%")
        )
    ).scalars().all()
    return list(rows)


def list_hopen_tech_recipients(session: Session) -> list[str]:
    """HopenTechBrief 일일 발송 채널 — `report_types LIKE '%hopen_tech%'` 또는 'all'."""
    rows = session.execute(
        select(Recipient.email)
        .where(Recipient.is_active.is_(True))
        .where(
            (Recipient.report_types == "all")
            | Recipient.report_types.like("%hopen_tech%")
        )
    ).scalars().all()
    return list(rows)


def _send_to_recipients(
    nl: Newsletter,
    recipients: list[str],
    *,
    dry_run: bool,
    sender_name: str,
    channel_label: str,
) -> SendSummary:
    """공통 발송 + sent_at 갱신 헬퍼."""
    with SessionLocal() as session:
        logger.info("%s 수신자 %d 명: %s", channel_label, len(recipients), recipients)

        if not recipients:
            return SendSummary(total=0, success=0, failed=0, failures=[])

        if dry_run:
            logger.info("dry_run=True — 실제 발송 안 함 (%s)", channel_label)
            return SendSummary(total=len(recipients), success=0, failed=0, failures=[])

        service = get_email_service()
        results: list[SendResult] = service.send_batch(
            recipients=recipients,
            subject=nl.subject,
            html_content=nl.html_body,
            sender_name=sender_name,
        )

        success = sum(1 for r in results if r.success)
        failures = [(r.recipient, r.error_message or "") for r in results if not r.success]

        if success > 0:
            nl_in_session = session.merge(nl)
            nl_in_session.sent_at = datetime.now(timezone.utc)
            session.commit()

        return SendSummary(
            total=len(results),
            success=success,
            failed=len(failures),
            failures=failures,
        )


def send_newsletter(nl: Newsletter, *, dry_run: bool = False) -> SendSummary:
    """주간 Insight Newsletter 발송 + sent_at 갱신."""
    with SessionLocal() as session:
        recipients = list_insight_recipients(session)
    return _send_to_recipients(
        nl, recipients, dry_run=dry_run,
        sender_name="StandUp Insight", channel_label="insight",
    )


def send_hopen_tech_brief(nl: Newsletter, *, dry_run: bool = False) -> SendSummary:
    """일일 HopenTechBrief 발송 + sent_at 갱신 (PR6)."""
    with SessionLocal() as session:
        recipients = list_hopen_tech_recipients(session)
    return _send_to_recipients(
        nl, recipients, dry_run=dry_run,
        sender_name="StandUp HopenTechBrief", channel_label="hopen_tech",
    )
