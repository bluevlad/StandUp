"""hopenvision_repo_indexer 단위 테스트 (PR4).

실제 hopenvision clone 에 의존하지 않도록 tmp_path 에 최소 Java/TS 트리를 생성.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.hopenvision_repo_indexer import (
    condense_for_prompt,
    index_hopenvision_repo,
)


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


@pytest.fixture()
def fake_hopen(tmp_path: Path) -> Path:
    """최소 HopenVision-like 구조."""
    api = tmp_path / "api" / "src" / "main" / "java" / "com" / "hopenvision"
    _write(
        api / "auth" / "AuthController.java",
        '''
        package com.hopenvision.auth;
        import org.springframework.web.bind.annotation.*;

        @RestController
        @RequestMapping("/api/auth")
        public class AuthController {
            // ...
        }
        ''',
    )
    _write(
        api / "user" / "User.java",
        '''
        package com.hopenvision.user;
        import jakarta.persistence.*;

        @Entity
        @Table(name = "users")
        public class User {
            @Id Long id;
        }
        ''',
    )
    _write(
        api / "enrollment" / "EnrollmentService.java",
        '''
        package com.hopenvision.enrollment;
        import org.springframework.stereotype.Service;

        @Service
        public class EnrollmentService { }
        ''',
    )
    # web-admin pages
    _write(
        tmp_path / "web-admin" / "src" / "pages" / "gosi" / "GosiList.tsx",
        "export default function GosiList() { return null; }",
    )
    _write(
        tmp_path / "web-admin" / "src" / "pages" / "Dashboard.tsx",
        "export default function Dashboard() { return null; }",
    )
    # web-user pages
    _write(
        tmp_path / "web-user" / "src" / "pages" / "GatewayLanding" / "index.tsx",
        "export default function Landing() { return null; }",
    )
    # noise: node_modules 는 제외돼야 함
    _write(
        tmp_path / "web-admin" / "node_modules" / "fake" / "x.tsx",
        "noise",
    )
    return tmp_path


def test_indexer_finds_controller_entity_service(fake_hopen, monkeypatch, tmp_path):
    # 캐시 디렉터리를 격리
    from app.services import hopenvision_repo_indexer as mod
    monkeypatch.setattr(mod.settings, "BASE_DIR", tmp_path / "standup")
    (tmp_path / "standup").mkdir()

    idx = index_hopenvision_repo(str(fake_hopen), force_refresh=True)
    classes = {c["class"] for c in idx["controllers"]}
    assert "AuthController" in classes
    ctrl = next(c for c in idx["controllers"] if c["class"] == "AuthController")
    assert ctrl["package"] == "com.hopenvision.auth"
    assert "/api/auth" in ctrl["routes"]

    ents = {e["class"]: e["table"] for e in idx["entities"]}
    assert ents.get("User") == "users"

    svcs = {s["class"] for s in idx["services"]}
    assert "EnrollmentService" in svcs


def test_indexer_finds_web_pages_and_skips_node_modules(fake_hopen, monkeypatch, tmp_path):
    from app.services import hopenvision_repo_indexer as mod
    monkeypatch.setattr(mod.settings, "BASE_DIR", tmp_path / "standup")
    (tmp_path / "standup").mkdir()

    idx = index_hopenvision_repo(str(fake_hopen), force_refresh=True)
    admin_names = {p["name"] for p in idx["web_admin_pages"]}
    assert "GosiList" in admin_names
    assert "Dashboard" in admin_names
    # index.tsx 는 상위 폴더명을 화면명으로
    user_names = {p["name"] for p in idx["web_user_pages"]}
    assert "GatewayLanding" in user_names
    # node_modules 는 색인 안 됨
    files = [p["file"] for p in idx["web_admin_pages"]]
    assert not any("node_modules" in f for f in files)


def test_indexer_uses_cache_within_ttl(fake_hopen, monkeypatch, tmp_path):
    from app.services import hopenvision_repo_indexer as mod
    monkeypatch.setattr(mod.settings, "BASE_DIR", tmp_path / "standup")
    (tmp_path / "standup").mkdir()

    idx1 = index_hopenvision_repo(str(fake_hopen), force_refresh=True)
    cache_file = tmp_path / "standup" / ".cache" / "hopenvision_repo_index.json"
    assert cache_file.exists()

    # 캐시 갱신 후 새 파일 추가 — 캐시 사용 시에는 못 찾아야 함
    new_ctrl = (
        fake_hopen / "api" / "src" / "main" / "java" / "com" / "hopenvision"
        / "extra" / "ExtraController.java"
    )
    _write(
        new_ctrl,
        '''
        package com.hopenvision.extra;
        import org.springframework.web.bind.annotation.*;

        @RestController
        @RequestMapping("/api/extra")
        public class ExtraController { }
        ''',
    )

    idx2 = index_hopenvision_repo(str(fake_hopen))  # force_refresh=False
    assert idx2["indexed_at"] == idx1["indexed_at"]
    assert "ExtraController" not in {c["class"] for c in idx2["controllers"]}

    # force_refresh 면 반영
    idx3 = index_hopenvision_repo(str(fake_hopen), force_refresh=True)
    assert "ExtraController" in {c["class"] for c in idx3["controllers"]}


def test_indexer_handles_missing_path():
    idx = index_hopenvision_repo("/nonexistent/path-xyz", force_refresh=True)
    assert idx["stale"] is True
    assert idx["summary"] == {}
    assert "경로 없음" in idx.get("warning", "")


def test_indexer_handles_empty_setting(monkeypatch):
    from app.services import hopenvision_repo_indexer as mod
    monkeypatch.setattr(mod.settings, "hopenvision_repo_path", "")
    idx = index_hopenvision_repo(None, force_refresh=True)
    assert idx["stale"] is True
    assert "미설정" in idx.get("warning", "")


def test_condense_for_prompt_summary_text(fake_hopen, monkeypatch, tmp_path):
    from app.services import hopenvision_repo_indexer as mod
    monkeypatch.setattr(mod.settings, "BASE_DIR", tmp_path / "standup")
    (tmp_path / "standup").mkdir()

    idx = index_hopenvision_repo(str(fake_hopen), force_refresh=True)
    text = condense_for_prompt(idx)
    assert "controllers=" in text
    assert "AuthController" in text
    assert "User" in text
    assert "GosiList" in text or "Dashboard" in text


def test_condense_for_prompt_handles_empty_index():
    text = condense_for_prompt({})
    assert "없음" in text
