"""HopenVision 레포 트리 인덱서 (PR4).

로컬 clone(`HOPENVISION_REPO_PATH`) 의 Spring(Java) + React(TS) 트리를 스캔해
LLM 프롬프트·적합도 평가에서 활용할 가벼운 인덱스를 만든다.

설계 원칙:
- **순수 파일시스템·정규식만 사용** — Java/TS 파서 의존성 없음. 가독성과 견고성을 위해
  *완벽한 시그니처 추출이 아닌* 키 메타데이터(클래스명·라우트·테이블 등)만 추출.
- **TTL 캐시** — `BASE_DIR/.cache/hopenvision_repo_index.json` 에 보관, 기본 24h.
  외부에서 `force_refresh=True` 호출 시 즉시 갱신.
- **부분 실패 흡수** — 단일 파일 파싱 오류는 로그만 남기고 다음으로 진행.

반환 dict 스키마:
```
{
  "repo_path": ".../hopenvision",
  "indexed_at": "ISO8601",
  "stale": false,
  "controllers": [{"class": "AuthController", "package": "com.hopenvision.auth",
                   "routes": ["/api/auth"], "file": "api/.../AuthController.java"}],
  "entities":    [{"class": "User", "table": "users",
                   "file": "api/.../entity/User.java"}],
  "services":    [{"class": "EnrollmentService", "file": "..."}],
  "web_admin_pages": [{"name": "GosiList", "file": "web-admin/src/pages/gosi/List.tsx"}],
  "web_user_pages":  [...],
  "summary":     {"controllers": 12, "entities": 30, ...}
}
```
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ..core.config import settings

logger = logging.getLogger(__name__)

# 인덱싱 대상에서 제외할 디렉터리 (.git, build artifact, node_modules 등)
_SKIP_DIRS = {
    ".git", ".idea", ".vscode", ".gradle", ".github",
    "build", "out", "target", "node_modules", "dist", ".next",
    "__pycache__", ".cache",
}

# Java 파일 1개를 부분 스캔할 때 읽을 최대 바이트 (성능 가드)
_JAVA_READ_LIMIT = 32 * 1024

_RE_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
_RE_CLASS = re.compile(r"\b(?:public\s+)?(?:abstract\s+)?class\s+(\w+)")
_RE_REST_CTRL = re.compile(r"@(?:RestController|Controller)\b")
_RE_REQUEST_MAPPING = re.compile(
    r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?[\{\["]?([^"\]\}\)]+)["\]\}]?',
)
_RE_ENTITY = re.compile(r"@Entity\b")
_RE_TABLE = re.compile(r'@Table\s*\([^)]*name\s*=\s*"([^"]+)"')
_RE_SERVICE = re.compile(r"@Service\b")


def _read_text_head(path: Path, limit: int = _JAVA_READ_LIMIT) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            return f.read(limit)
    except OSError as e:
        logger.debug("read fail %s: %s", path, e)
        return ""


def _iter_files(root: Path, exts: tuple[str, ...]) -> list[Path]:
    """root 아래에서 _SKIP_DIRS 를 건너뛰며 확장자 매칭."""
    out: list[Path] = []
    if not root.exists():
        return out
    for p in root.rglob("*"):
        # 중간 경로에 skip 디렉터리가 있으면 제외
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if p.is_file() and p.suffix in exts:
            out.append(p)
    return out


def _scan_java(repo_path: Path) -> tuple[list[dict], list[dict], list[dict]]:
    """api/src/main/java 트리에서 controller/entity/service 추출."""
    api_root = repo_path / "api" / "src" / "main" / "java"
    controllers: list[dict] = []
    entities: list[dict] = []
    services: list[dict] = []

    for jf in _iter_files(api_root, (".java",)):
        text = _read_text_head(jf)
        if not text:
            continue
        rel = jf.relative_to(repo_path).as_posix()
        pkg_m = _RE_PACKAGE.search(text)
        cls_m = _RE_CLASS.search(text)
        if not cls_m:
            continue
        cls_name = cls_m.group(1)
        package = pkg_m.group(1) if pkg_m else ""

        if _RE_REST_CTRL.search(text):
            routes = [m.group(1).strip() for m in _RE_REQUEST_MAPPING.finditer(text)]
            controllers.append({
                "class": cls_name,
                "package": package,
                "routes": routes,
                "file": rel,
            })
        if _RE_ENTITY.search(text):
            table_m = _RE_TABLE.search(text)
            entities.append({
                "class": cls_name,
                "table": table_m.group(1) if table_m else "",
                "file": rel,
            })
        # service 는 controller 와 동시 매칭 가능 (드물지만)
        if _RE_SERVICE.search(text):
            services.append({"class": cls_name, "file": rel})

    return controllers, entities, services


def _scan_web_pages(repo_path: Path, dir_name: str) -> list[dict]:
    """web-admin / web-user / web-shared 의 pages 디렉터리에서 페이지 컴포넌트 추출.

    파일명을 그대로 화면명으로 사용 — 정확한 react-router 라우트 매칭은 PR5 에서.
    """
    pages_root = repo_path / dir_name / "src" / "pages"
    out: list[dict] = []
    for tf in _iter_files(pages_root, (".tsx", ".ts", ".jsx")):
        rel = tf.relative_to(repo_path).as_posix()
        # `index.tsx` 는 상위 폴더명을 화면명으로 사용
        if tf.stem.lower() in ("index", "router"):
            name = tf.parent.name
        else:
            name = tf.stem
        out.append({"name": name, "file": rel})
    return out


def _cache_path() -> Path:
    cache_dir = settings.BASE_DIR / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "hopenvision_repo_index.json"


def _is_cache_fresh(path: Path, ttl_hours: int) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ts = data.get("indexed_at")
        if not ts:
            return False
        ts_dt = datetime.fromisoformat(ts)
        if ts_dt.tzinfo is None:
            ts_dt = ts_dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - ts_dt < timedelta(hours=ttl_hours)
    except (json.JSONDecodeError, ValueError, OSError):
        return False


def _empty_index(repo_path: str, reason: str) -> dict:
    return {
        "repo_path": repo_path,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "stale": True,
        "controllers": [],
        "entities": [],
        "services": [],
        "web_admin_pages": [],
        "web_user_pages": [],
        "web_shared_pages": [],
        "summary": {},
        "warning": reason,
    }


def index_hopenvision_repo(
    repo_path: Optional[str] = None,
    *,
    force_refresh: bool = False,
    ttl_hours: Optional[int] = None,
) -> dict:
    """HopenVision 레포 트리를 인덱싱 (캐시 우선).

    Args:
        repo_path: HopenVision 로컬 경로. None 이면 `settings.hopenvision_repo_path`.
        force_refresh: 캐시 무시.
        ttl_hours: 캐시 TTL. None 이면 settings.

    Returns:
        인덱스 dict (스키마: 모듈 docstring 참고).
    """
    rp_str = repo_path if repo_path is not None else settings.hopenvision_repo_path
    ttl = ttl_hours if ttl_hours is not None else settings.hopen_repo_index_ttl_hours

    if not rp_str:
        return _empty_index("", "HOPENVISION_REPO_PATH 미설정")

    rp = Path(rp_str).expanduser()
    if not rp.exists() or not rp.is_dir():
        return _empty_index(str(rp), f"경로 없음: {rp}")

    cache_file = _cache_path()
    if not force_refresh and _is_cache_fresh(cache_file, ttl):
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            data["stale"] = False
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("repo index 캐시 읽기 실패, 재생성: %s", e)

    controllers, entities, services = _scan_java(rp)
    admin_pages = _scan_web_pages(rp, "web-admin")
    user_pages = _scan_web_pages(rp, "web-user")
    shared_pages = _scan_web_pages(rp, "web-shared")

    index = {
        "repo_path": str(rp),
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "stale": False,
        "controllers": controllers,
        "entities": entities,
        "services": services,
        "web_admin_pages": admin_pages,
        "web_user_pages": user_pages,
        "web_shared_pages": shared_pages,
        "summary": {
            "controllers": len(controllers),
            "entities": len(entities),
            "services": len(services),
            "web_admin_pages": len(admin_pages),
            "web_user_pages": len(user_pages),
            "web_shared_pages": len(shared_pages),
        },
    }

    try:
        cache_file.write_text(
            json.dumps(index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("repo index 캐시 저장 실패: %s", e)

    logger.info(
        "hopenvision repo indexed: %s (controllers=%d entities=%d services=%d "
        "admin_pages=%d user_pages=%d)",
        rp.name, len(controllers), len(entities), len(services),
        len(admin_pages), len(user_pages),
    )
    return index


def condense_for_prompt(index: dict, *, max_per_section: int = 12) -> str:
    """LLM 프롬프트용 압축 텍스트 — controllers/entities/pages 핵심만 줄로 나열."""
    if not index or not index.get("summary"):
        return "(HopenVision repo index 없음)"

    lines: list[str] = []
    s = index["summary"]
    lines.append(
        f"[HopenVision repo index] controllers={s.get('controllers', 0)} "
        f"entities={s.get('entities', 0)} services={s.get('services', 0)} "
        f"admin_pages={s.get('web_admin_pages', 0)} "
        f"user_pages={s.get('web_user_pages', 0)}"
    )

    ctrls = index.get("controllers", [])[:max_per_section]
    if ctrls:
        lines.append("· 컨트롤러:")
        for c in ctrls:
            routes = ",".join(c.get("routes", [])) or "-"
            lines.append(f"  - {c['class']} ({routes})")

    ents = index.get("entities", [])[:max_per_section]
    if ents:
        lines.append("· 엔티티:")
        for e in ents:
            tbl = e.get("table") or "-"
            lines.append(f"  - {e['class']} (table={tbl})")

    admin = index.get("web_admin_pages", [])[:max_per_section]
    if admin:
        lines.append("· web-admin pages: " + ", ".join(p["name"] for p in admin))
    user = index.get("web_user_pages", [])[:max_per_section]
    if user:
        lines.append("· web-user pages: " + ", ".join(p["name"] for p in user))

    return "\n".join(lines)
