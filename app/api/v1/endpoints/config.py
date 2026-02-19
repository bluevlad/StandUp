"""
설정 관리 CRUD API
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ....core.database import get_db
from ....models.git_provider import GitProvider, ProviderType
from ....models.repository import Repository
from ....models.recipient import Recipient
from ....models.app_setting import AppSetting
from ....schemas.config import (
    GitProviderCreate, GitProviderUpdate, GitProviderResponse,
    RepositoryCreate, RepositoryUpdate, RepositoryResponse,
    RecipientCreate, RecipientUpdate, RecipientResponse,
    AppSettingUpdate, AppSettingBulkUpdate, AppSettingResponse,
    SetupStatusResponse,
)
from ....services import config_service
from ....services.github_service import GitHubService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["설정 관리"])


# ============================================================
# Git Providers
# ============================================================

@router.get("/git-providers", response_model=list[GitProviderResponse])
def list_git_providers(db: Session = Depends(get_db)):
    """Git 프로바이더 목록 조회"""
    return db.query(GitProvider).order_by(GitProvider.id).all()


@router.post("/git-providers", response_model=GitProviderResponse, status_code=201)
def create_git_provider(data: GitProviderCreate, db: Session = Depends(get_db)):
    """Git 프로바이더 등록"""
    provider = GitProvider(
        name=data.name,
        provider_type=ProviderType(data.provider_type),
        base_url=data.base_url,
        token=data.token,
        org_name=data.org_name,
        is_active=data.is_active,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return provider


@router.get("/git-providers/{provider_id}", response_model=GitProviderResponse)
def get_git_provider(provider_id: int, db: Session = Depends(get_db)):
    """Git 프로바이더 상세 조회"""
    provider = db.query(GitProvider).filter(GitProvider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Git 프로바이더를 찾을 수 없습니다.")
    return provider


@router.put("/git-providers/{provider_id}", response_model=GitProviderResponse)
def update_git_provider(provider_id: int, data: GitProviderUpdate, db: Session = Depends(get_db)):
    """Git 프로바이더 수정"""
    provider = db.query(GitProvider).filter(GitProvider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Git 프로바이더를 찾을 수 없습니다.")

    update_data = data.model_dump(exclude_unset=True)
    if "provider_type" in update_data:
        update_data["provider_type"] = ProviderType(update_data["provider_type"])
    for key, value in update_data.items():
        setattr(provider, key, value)

    db.commit()
    db.refresh(provider)
    return provider


@router.delete("/git-providers/{provider_id}")
def delete_git_provider(provider_id: int, db: Session = Depends(get_db)):
    """Git 프로바이더 삭제 (CASCADE → 연결된 리포도 삭제)"""
    provider = db.query(GitProvider).filter(GitProvider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Git 프로바이더를 찾을 수 없습니다.")

    db.delete(provider)
    db.commit()
    return {"message": f"'{provider.name}' 프로바이더가 삭제되었습니다."}


@router.post("/git-providers/{provider_id}/sync-repos")
def sync_repos(provider_id: int, db: Session = Depends(get_db)):
    """프로바이더의 리포지토리 자동 발견 및 동기화"""
    provider = db.query(GitProvider).filter(GitProvider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Git 프로바이더를 찾을 수 없습니다.")

    if provider.provider_type != ProviderType.GITHUB:
        raise HTTPException(status_code=400, detail="현재 GitHub만 지원합니다.")

    github = GitHubService(
        token=provider.token,
        org_name=provider.org_name,
        base_url=provider.base_url,
    )
    repos = github.get_org_repos()

    added = 0
    skipped = 0
    for repo_data in repos:
        existing = db.query(Repository).filter(
            Repository.git_provider_id == provider_id,
            Repository.repo_full_name == repo_data["full_name"],
        ).first()

        if existing:
            skipped += 1
            continue

        repo = Repository(
            git_provider_id=provider_id,
            repo_name=repo_data["name"],
            repo_full_name=repo_data["full_name"],
            repo_url=repo_data["url"],
        )
        db.add(repo)
        added += 1

    db.commit()
    return {
        "message": f"리포지토리 동기화 완료",
        "added": added,
        "skipped": skipped,
        "total": len(repos),
    }


# ============================================================
# Repositories
# ============================================================

@router.get("/repositories", response_model=list[RepositoryResponse])
def list_repositories(
    git_provider_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """리포지토리 목록 조회"""
    query = db.query(Repository).order_by(Repository.id)
    if git_provider_id is not None:
        query = query.filter(Repository.git_provider_id == git_provider_id)
    return query.all()


@router.post("/repositories", response_model=RepositoryResponse, status_code=201)
def create_repository(data: RepositoryCreate, db: Session = Depends(get_db)):
    """리포지토리 등록"""
    # FK 검증
    provider = db.query(GitProvider).filter(GitProvider.id == data.git_provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Git 프로바이더를 찾을 수 없습니다.")

    repo = Repository(
        git_provider_id=data.git_provider_id,
        repo_name=data.repo_name,
        repo_full_name=data.repo_full_name,
        repo_url=data.repo_url,
        is_active=data.is_active,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return repo


@router.get("/repositories/{repo_id}", response_model=RepositoryResponse)
def get_repository(repo_id: int, db: Session = Depends(get_db)):
    """리포지토리 상세 조회"""
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="리포지토리를 찾을 수 없습니다.")
    return repo


@router.put("/repositories/{repo_id}", response_model=RepositoryResponse)
def update_repository(repo_id: int, data: RepositoryUpdate, db: Session = Depends(get_db)):
    """리포지토리 수정"""
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="리포지토리를 찾을 수 없습니다.")

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(repo, key, value)

    db.commit()
    db.refresh(repo)
    return repo


@router.delete("/repositories/{repo_id}")
def delete_repository(repo_id: int, db: Session = Depends(get_db)):
    """리포지토리 삭제"""
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="리포지토리를 찾을 수 없습니다.")

    db.delete(repo)
    db.commit()
    return {"message": f"'{repo.repo_full_name}' 리포지토리가 삭제되었습니다."}


# ============================================================
# Recipients
# ============================================================

@router.get("/recipients", response_model=list[RecipientResponse])
def list_recipients(db: Session = Depends(get_db)):
    """수신자 목록 조회"""
    return db.query(Recipient).order_by(Recipient.id).all()


@router.post("/recipients", response_model=RecipientResponse, status_code=201)
def create_recipient(data: RecipientCreate, db: Session = Depends(get_db)):
    """수신자 등록"""
    existing = db.query(Recipient).filter(Recipient.email == data.email).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"이미 등록된 이메일입니다: {data.email}")

    recipient = Recipient(
        name=data.name,
        email=data.email,
        report_types=data.report_types,
        is_active=data.is_active,
    )
    db.add(recipient)
    db.commit()
    db.refresh(recipient)
    return recipient


@router.get("/recipients/{recipient_id}", response_model=RecipientResponse)
def get_recipient(recipient_id: int, db: Session = Depends(get_db)):
    """수신자 상세 조회"""
    recipient = db.query(Recipient).filter(Recipient.id == recipient_id).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="수신자를 찾을 수 없습니다.")
    return recipient


@router.put("/recipients/{recipient_id}", response_model=RecipientResponse)
def update_recipient(recipient_id: int, data: RecipientUpdate, db: Session = Depends(get_db)):
    """수신자 수정"""
    recipient = db.query(Recipient).filter(Recipient.id == recipient_id).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="수신자를 찾을 수 없습니다.")

    update_data = data.model_dump(exclude_unset=True)
    if "email" in update_data:
        dup = db.query(Recipient).filter(
            Recipient.email == update_data["email"],
            Recipient.id != recipient_id,
        ).first()
        if dup:
            raise HTTPException(status_code=409, detail=f"이미 등록된 이메일입니다: {update_data['email']}")

    for key, value in update_data.items():
        setattr(recipient, key, value)

    db.commit()
    db.refresh(recipient)
    return recipient


@router.delete("/recipients/{recipient_id}")
def delete_recipient(recipient_id: int, db: Session = Depends(get_db)):
    """수신자 삭제"""
    recipient = db.query(Recipient).filter(Recipient.id == recipient_id).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="수신자를 찾을 수 없습니다.")

    db.delete(recipient)
    db.commit()
    return {"message": f"'{recipient.name}' 수신자가 삭제되었습니다."}


# ============================================================
# App Settings
# ============================================================

@router.get("/settings", response_model=list[AppSettingResponse])
def list_settings(category: Optional[str] = None, db: Session = Depends(get_db)):
    """앱 설정 목록 조회 (카테고리 필터 가능)"""
    query = db.query(AppSetting).order_by(AppSetting.category, AppSetting.key)
    if category:
        query = query.filter(AppSetting.category == category)
    return query.all()


@router.get("/settings/{key}", response_model=AppSettingResponse)
def get_setting(key: str, db: Session = Depends(get_db)):
    """설정 조회"""
    setting = db.query(AppSetting).filter(AppSetting.key == key).first()
    if not setting:
        raise HTTPException(status_code=404, detail=f"설정을 찾을 수 없습니다: {key}")
    return setting


@router.put("/settings/{key}", response_model=AppSettingResponse)
def update_setting(key: str, data: AppSettingUpdate, db: Session = Depends(get_db)):
    """설정 수정 (없으면 생성)"""
    setting = db.query(AppSetting).filter(AppSetting.key == key).first()
    if setting:
        setting.value = data.value
        if data.value_type is not None:
            setting.value_type = data.value_type
        if data.category is not None:
            setting.category = data.category
        if data.description is not None:
            setting.description = data.description
    else:
        setting = AppSetting(
            key=key,
            value=data.value,
            value_type=data.value_type or "string",
            category=data.category or "general",
            description=data.description,
        )
        db.add(setting)

    db.commit()
    db.refresh(setting)
    return setting


@router.put("/settings", response_model=list[AppSettingResponse])
def bulk_update_settings(data: AppSettingBulkUpdate, db: Session = Depends(get_db)):
    """설정 일괄 업데이트"""
    results = []
    for item in data.settings:
        key = item.get("key")
        value = item.get("value")
        if not key or value is None:
            continue

        setting = db.query(AppSetting).filter(AppSetting.key == key).first()
        if setting:
            setting.value = str(value)
        else:
            setting = AppSetting(key=key, value=str(value))
            db.add(setting)
        db.flush()
        results.append(setting)

    db.commit()
    for s in results:
        db.refresh(s)
    return results


# ============================================================
# Setup / Seed
# ============================================================

@router.get("/setup-status", response_model=SetupStatusResponse)
def get_setup_status(db: Session = Depends(get_db)):
    """초기화 상태 확인"""
    providers = db.query(GitProvider).filter(GitProvider.is_active == True).count()  # noqa: E712
    repos = db.query(Repository).filter(Repository.is_active == True).count()  # noqa: E712
    recipients = db.query(Recipient).filter(Recipient.is_active == True).count()  # noqa: E712
    settings_count = db.query(AppSetting).count()

    return SetupStatusResponse(
        git_providers_configured=providers > 0,
        repositories_count=repos,
        recipients_configured=recipients > 0,
        recipients_count=recipients,
        app_settings_count=settings_count,
        is_ready=providers > 0 and recipients > 0,
    )


@router.post("/seed")
def seed_from_env(db: Session = Depends(get_db)):
    """.env 값을 DB로 시드 (멱등)"""
    result = config_service.seed_from_env(db)
    return result
