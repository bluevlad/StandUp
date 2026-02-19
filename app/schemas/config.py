"""
설정 관리 Pydantic 스키마
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


# ============================================================
# Git Provider
# ============================================================

class GitProviderCreate(BaseModel):
    name: str = Field(..., max_length=100)
    provider_type: str = Field(default="github", pattern="^(github|gitlab)$")
    base_url: Optional[str] = Field(None, max_length=500)
    token: str = Field(..., max_length=500)
    org_name: str = Field(..., max_length=200)
    is_active: bool = True


class GitProviderUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    provider_type: Optional[str] = Field(None, pattern="^(github|gitlab)$")
    base_url: Optional[str] = Field(None, max_length=500)
    token: Optional[str] = Field(None, max_length=500)
    org_name: Optional[str] = Field(None, max_length=200)
    is_active: Optional[bool] = None


class GitProviderResponse(BaseModel):
    """응답 스키마 - token 필드 제외 (보안)"""
    id: int
    name: str
    provider_type: str
    base_url: Optional[str]
    org_name: str
    is_active: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ============================================================
# Repository
# ============================================================

class RepositoryCreate(BaseModel):
    git_provider_id: int
    repo_name: str = Field(..., max_length=200)
    repo_full_name: str = Field(..., max_length=500)
    repo_url: Optional[str] = Field(None, max_length=500)
    is_active: bool = True


class RepositoryUpdate(BaseModel):
    repo_name: Optional[str] = Field(None, max_length=200)
    repo_full_name: Optional[str] = Field(None, max_length=500)
    repo_url: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None


class RepositoryResponse(BaseModel):
    id: int
    git_provider_id: int
    repo_name: str
    repo_full_name: str
    repo_url: Optional[str]
    is_active: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ============================================================
# Recipient
# ============================================================

class RecipientCreate(BaseModel):
    name: str = Field(..., max_length=200)
    email: EmailStr
    report_types: str = Field(default="all", max_length=100)
    is_active: bool = True


class RecipientUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    email: Optional[EmailStr] = None
    report_types: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None


class RecipientResponse(BaseModel):
    id: int
    name: str
    email: str
    report_types: str
    is_active: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ============================================================
# App Setting
# ============================================================

class AppSettingUpdate(BaseModel):
    value: str = Field(..., max_length=1000)
    value_type: Optional[str] = Field(None, max_length=20)
    category: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = Field(None, max_length=500)


class AppSettingBulkUpdate(BaseModel):
    """일괄 업데이트용"""
    settings: list[dict] = Field(
        ...,
        description="[{key: str, value: str}, ...]"
    )


class AppSettingResponse(BaseModel):
    id: int
    key: str
    value: str
    value_type: str
    category: str
    description: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ============================================================
# Setup Status
# ============================================================

class SetupStatusResponse(BaseModel):
    git_providers_configured: bool
    repositories_count: int
    recipients_configured: bool
    recipients_count: int
    app_settings_count: int
    is_ready: bool
