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
