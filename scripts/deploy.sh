#!/bin/bash
set -euo pipefail

# ============================================================
# StandUp Production Deploy Script
# prod 브랜치 push 시 GitHub Actions Self-hosted Runner에서 실행
# ============================================================

APP_NAME="standup-app"
COMPOSE_FILE="docker-compose.production.yml"
LOG_PREFIX="[StandUp Deploy]"

log() {
    echo "${LOG_PREFIX} $(date '+%Y-%m-%d %H:%M:%S') $1"
}

error_exit() {
    log "ERROR: $1"
    exit 1
}

# 1. 사전 검증
log "Starting deployment..."

if [ ! -f "${COMPOSE_FILE}" ]; then
    error_exit "${COMPOSE_FILE} not found"
fi

if [ ! -f ".env.production" ]; then
    error_exit ".env.production not found"
fi

# 2. Docker 네트워크 확인 (unmong-network)
if ! docker network ls --format '{{.Name}}' | grep -q "^unmong-network$"; then
    log "Creating Docker network 'unmong-network'..."
    docker network create unmong-network || error_exit "Failed to create network"
fi

# 3. 이전 컨테이너 상태 확인
PREVIOUS_IMAGE=""
if docker ps -a --format '{{.Names}}' | grep -q "^${APP_NAME}$"; then
    PREVIOUS_IMAGE=$(docker inspect --format='{{.Image}}' "${APP_NAME}" 2>/dev/null || true)
    log "Previous container found (image: ${PREVIOUS_IMAGE})"
fi

# 4. Docker 이미지 빌드
log "Building Docker image..."
docker compose -f "${COMPOSE_FILE}" build --no-cache || error_exit "Docker build failed"

# 5. DB 마이그레이션 실행
log "Running database migrations..."
docker compose -f "${COMPOSE_FILE}" run --rm --no-deps standup \
    alembic upgrade head 2>&1 || log "WARNING: Migration skipped or failed (may already be up to date)"

# 6. 기존 컨테이너 중지 및 재시작
log "Stopping existing container..."
docker compose -f "${COMPOSE_FILE}" down --timeout 30 2>/dev/null || true

log "Starting new container..."
docker compose -f "${COMPOSE_FILE}" up -d || error_exit "Failed to start container"

# 7. 기동 확인
log "Verifying container status..."
sleep 5

if docker ps --format '{{.Names}}' | grep -q "^${APP_NAME}$"; then
    log "Container '${APP_NAME}' is running"
else
    log "Container failed to start. Logs:"
    docker logs "${APP_NAME}" --tail 30 2>&1 || true
    error_exit "Container is not running"
fi

# 8. 이전 이미지 정리
if [ -n "${PREVIOUS_IMAGE}" ]; then
    log "Cleaning up dangling images..."
    docker image prune -f 2>/dev/null || true
fi

log "Deployment completed successfully!"
log "Service: http://localhost:9060"
log "Health:  http://localhost:9060/api/v1/health"
log "Docs:    http://localhost:9060/docs"
