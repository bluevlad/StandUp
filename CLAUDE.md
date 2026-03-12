# StandUp - 업무관리 자동화 Agent

## Project Overview
Git Issues 기반 업무 수집, 분류, 보고서 자동 생성/발송 시스템

## Environment
- DB: PostgreSQL 15 (별도 서버, .env로 관리)
  - Production: `standup`
  - Development: `standup_dev`
- Docker: DB-first (DB는 별도 서버, 앱은 Docker 실행)
- Python: 3.11+

## Tech Stack
- Language: Python 3.11+
- Framework: FastAPI
- ORM: SQLAlchemy 2.0 + Alembic
- Database: PostgreSQL 15 (psycopg2-binary)
- Scheduler: APScheduler
- Email: smtplib + aiosmtplib (Gmail SMTP)
- Template: Jinja2
- GitHub API: PyGithub
- Config: pydantic-settings + python-dotenv

## Build and Run
```bash
# 가상환경
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# 의존성 설치
pip install -r requirements.txt

# DB 마이그레이션
alembic upgrade head

# 실행
python -m uvicorn app.main:app --host 0.0.0.0 --port 9060 --reload
```

## Project Structure
```
app/
├── agents/           # QA-Agent, Tobe-Agent, Report-Agent
├── core/             # config, database, scheduler
├── models/           # SQLAlchemy ORM 모델
├── schemas/          # Pydantic 스키마
├── services/         # GitHub, Email, Report 서비스
├── templates/        # Jinja2 이메일 템플릿
└── api/v1/endpoints/ # FastAPI 라우터
```

## Do NOT
- Oracle 문법 사용 금지 (NVL, SYSDATE, ROWNUM 등)
- .env 파일을 git에 커밋 금지
- docker-compose.production.yml을 개발 PC에서 수정 금지
- 운영 DB에 직접 DDL 실행 금지

## Database Notes
- PostgreSQL 전용: COALESCE, NOW(), LIMIT/OFFSET 사용
- 테이블명: snake_case
- FK 명명: fk_{테이블}_{참조테이블}

## Port
- API: 9060

## Fix 커밋 오류 추적

> 상세: [FIX_COMMIT_TRACKING_GUIDE.md](https://github.com/bluevlad/Claude-Opus-bluevlad/blob/main/standards/git/FIX_COMMIT_TRACKING_GUIDE.md) | [ERROR_TAXONOMY.md](https://github.com/bluevlad/Claude-Opus-bluevlad/blob/main/standards/git/ERROR_TAXONOMY.md)

`fix:` 커밋 시 footer에 오류 추적 메타데이터를 **필수** 포함합니다.

### 이 프로젝트에서 자주 발생하는 Root-Cause

| Root-Cause | 설명 | 예방 |
|-----------|------|------|
| `env-assumption` | Docker 내/외부 경로, 환경변수 가정 | Settings 클래스에서 필수값 검증, 기본값 금지 |
| `import-error` | 패키지 import 경로 오류, 상대/절대 경로 혼동 | `__init__.py` 확인, 절대 import 사용 |
| `null-handling` | Optional 필드 None 미처리 | Pydantic `Optional[T]` + 기본값 명시 |
| `type-mismatch` | SQLAlchemy 모델 ↔ Pydantic 스키마 타입 불일치 | `model_validate()` 사용, from_attributes=True |
| `async-handling` | await 누락, 동기/비동기 혼용 | async def에서 동기 DB 호출 금지, run_in_executor 사용 |
| `db-migration` | Alembic 마이그레이션 누락/충돌 | 스키마 변경 시 반드시 `alembic revision --autogenerate` |

### 예시

```
fix(api): 알레르기 성분 조회 시 None 응답 처리

- ingredient가 Optional인데 None 체크 없이 .name 접근하여 AttributeError 발생
- None일 때 빈 문자열 반환하도록 수정

Root-Cause: null-handling
Error-Category: logic-error
Affected-Layer: backend/api
Recurrence: first
Prevention: Optional 필드 접근 전 반드시 None 체크, or 연산자 활용

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```
