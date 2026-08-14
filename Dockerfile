FROM python:3.12-slim

WORKDIR /app

# Timezone 설정 (스케줄러, 로그 타임스탬프 등 KST 통일)
ENV TZ=Asia/Seoul
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# System dependencies
# - libpq-dev: PostgreSQL client lib for psycopg2
# - git: claude-sessions ingest 가 마운트된 호스트 GIT 디렉토리에서 git log 호출
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Mounted host dirs 는 다른 UID 로 보이므로 git 의 dubious ownership 경고 우회
RUN git config --system --add safe.directory '*'

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Create log directory
RUN mkdir -p /app/logs

EXPOSE 9065

# Health check
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9065/api/v1/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9065"]
