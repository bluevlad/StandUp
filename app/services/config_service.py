"""
설정 관리 서비스 - DB-first, .env fallback
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from ..core.config import settings
from ..models.git_provider import GitProvider
from ..models.repository import Repository
from ..models.recipient import Recipient
from ..models.app_setting import AppSetting

logger = logging.getLogger(__name__)


def get_setting(db: Session, key: str, default: str = None) -> Optional[str]:
    """DB에서 설정 조회, 없으면 .env fallback"""
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        return row.value

    # .env fallback
    env_map = {
        "gmail_address": settings.gmail_address,
        "gmail_app_password": settings.gmail_app_password,
        "daily_report_hour": str(settings.daily_report_hour),
        "daily_report_minute": str(settings.daily_report_minute),
        "weekly_report_hour": str(settings.weekly_report_hour),
        "weekly_report_minute": str(settings.weekly_report_minute),
        "monthly_report_hour": str(settings.monthly_report_hour),
        "monthly_report_minute": str(settings.monthly_report_minute),
        "max_projects_per_category": str(settings.max_projects_per_category),
        "max_items_per_project": str(settings.max_items_per_project),
    }
    return env_map.get(key, default)


def get_setting_int(db: Session, key: str, default: int = 0) -> int:
    """정수 설정 조회"""
    value = get_setting(db, key)
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def get_setting_bool(db: Session, key: str, default: bool = False) -> bool:
    """불리언 설정 조회"""
    value = get_setting(db, key)
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes")


def get_active_recipients(db: Session, report_type: str = None) -> list[str]:
    """활성 수신자 이메일 목록 조회 (DB → .env fallback)"""
    recipients = db.query(Recipient).filter(Recipient.is_active == True).all()  # noqa: E712

    if recipients:
        if report_type:
            return [
                r.email for r in recipients
                if r.report_types == "all" or report_type in r.report_types.split(",")
            ]
        return [r.email for r in recipients]

    # .env fallback
    return settings.recipient_list


def get_active_git_providers(db: Session) -> list[GitProvider]:
    """활성 Git 프로바이더 목록 조회"""
    return db.query(GitProvider).filter(GitProvider.is_active == True).all()  # noqa: E712


def get_active_repositories(db: Session, provider_id: int = None) -> list[Repository]:
    """활성 리포지토리 목록 조회"""
    query = db.query(Repository).filter(Repository.is_active == True)  # noqa: E712
    if provider_id:
        query = query.filter(Repository.git_provider_id == provider_id)
    return query.all()


def get_gmail_config(db: Session) -> dict:
    """Gmail 설정 조회 (DB → .env fallback)"""
    address = get_setting(db, "gmail_address")
    password = get_setting(db, "gmail_app_password")
    return {
        "address": address or "",
        "password": password or "",
    }


def seed_from_env(db: Session) -> dict:
    """
    .env 값을 DB로 시드 (멱등 - 이미 있으면 건너뜀)
    Returns: {seeded: [...], skipped: [...]}
    """
    seeded = []
    skipped = []

    # 1. Git Provider 시드
    if settings.github_token and settings.github_org:
        existing = db.query(GitProvider).filter(
            GitProvider.org_name == settings.github_org
        ).first()
        if not existing:
            provider = GitProvider(
                name=f"{settings.github_org} GitHub",
                provider_type="GITHUB",
                token=settings.github_token,
                org_name=settings.github_org,
            )
            db.add(provider)
            db.flush()
            seeded.append(f"git_provider: {settings.github_org}")
        else:
            skipped.append(f"git_provider: {settings.github_org} (이미 존재)")

    # 2. Recipients 시드
    for email in settings.recipient_list:
        existing = db.query(Recipient).filter(Recipient.email == email).first()
        if not existing:
            name = email.split("@")[0]
            recipient = Recipient(name=name, email=email)
            db.add(recipient)
            seeded.append(f"recipient: {email}")
        else:
            skipped.append(f"recipient: {email} (이미 존재)")

    # 3. App Settings 시드
    setting_seeds = [
        ("gmail_address", settings.gmail_address, "string", "email", "Gmail 발송 주소"),
        ("gmail_app_password", settings.gmail_app_password, "string", "email", "Gmail 앱 비밀번호"),
        ("daily_report_hour", str(settings.daily_report_hour), "int", "scheduler", "일일보고 시간 (시)"),
        ("daily_report_minute", str(settings.daily_report_minute), "int", "scheduler", "일일보고 시간 (분)"),
        ("weekly_report_hour", str(settings.weekly_report_hour), "int", "scheduler", "주간보고 시간 (시)"),
        ("weekly_report_minute", str(settings.weekly_report_minute), "int", "scheduler", "주간보고 시간 (분)"),
        ("monthly_report_hour", str(settings.monthly_report_hour), "int", "scheduler", "월간보고 시간 (시)"),
        ("monthly_report_minute", str(settings.monthly_report_minute), "int", "scheduler", "월간보고 시간 (분)"),
        ("max_projects_per_category", str(settings.max_projects_per_category), "int", "report", "카테고리당 최대 프로젝트 수"),
        ("max_items_per_project", str(settings.max_items_per_project), "int", "report", "프로젝트당 최대 항목 수"),
    ]

    for key, value, value_type, category, description in setting_seeds:
        if not value:
            skipped.append(f"setting: {key} (값 없음)")
            continue
        existing = db.query(AppSetting).filter(AppSetting.key == key).first()
        if not existing:
            setting = AppSetting(
                key=key,
                value=value,
                value_type=value_type,
                category=category,
                description=description,
            )
            db.add(setting)
            seeded.append(f"setting: {key}")
        else:
            skipped.append(f"setting: {key} (이미 존재)")

    db.commit()
    logger.info(f"시드 완료: {len(seeded)}건 추가, {len(skipped)}건 건너뜀")
    return {"seeded": seeded, "skipped": skipped}
