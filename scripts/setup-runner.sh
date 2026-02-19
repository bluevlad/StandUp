#!/bin/bash
set -euo pipefail

# ============================================================
# GitHub Actions Self-hosted Runner 설치 스크립트
# 운영 MacBook에서 한 번만 실행
# ============================================================

REPO_URL="https://github.com/bluevlad/StandUp"
RUNNER_DIR="$HOME/actions-runner"

echo "========================================"
echo " GitHub Actions Self-hosted Runner 설치"
echo "========================================"
echo ""

# 1. Runner 디렉토리 생성
if [ -d "${RUNNER_DIR}" ]; then
    echo "Runner directory already exists: ${RUNNER_DIR}"
    echo "Remove it first if you want to reinstall: rm -rf ${RUNNER_DIR}"
    exit 1
fi

mkdir -p "${RUNNER_DIR}"
cd "${RUNNER_DIR}"

# 2. 최신 Runner 다운로드 (macOS ARM64)
echo "Downloading GitHub Actions Runner..."
ARCH=$(uname -m)
if [ "${ARCH}" = "arm64" ]; then
    RUNNER_ARCH="osx-arm64"
else
    RUNNER_ARCH="osx-x64"
fi

# 최신 버전 확인 및 다운로드
LATEST_VERSION=$(curl -s https://api.github.com/repos/actions/runner/releases/latest | grep '"tag_name"' | sed -E 's/.*"v([^"]+)".*/\1/')
DOWNLOAD_URL="https://github.com/actions/runner/releases/download/v${LATEST_VERSION}/actions-runner-${RUNNER_ARCH}-${LATEST_VERSION}.tar.gz"

echo "Version: ${LATEST_VERSION}"
echo "Architecture: ${RUNNER_ARCH}"
curl -o actions-runner.tar.gz -L "${DOWNLOAD_URL}"
tar xzf actions-runner.tar.gz
rm actions-runner.tar.gz

# 3. Runner 등록 안내
echo ""
echo "========================================"
echo " Runner 등록 방법"
echo "========================================"
echo ""
echo "1. GitHub에서 토큰 발급:"
echo "   ${REPO_URL}/settings/actions/runners/new"
echo ""
echo "2. 아래 명령어로 Runner 등록:"
echo "   cd ${RUNNER_DIR}"
echo "   ./config.sh --url ${REPO_URL} --token <YOUR_TOKEN>"
echo ""
echo "3. Runner를 서비스로 등록 (자동 시작):"
echo "   cd ${RUNNER_DIR}"
echo "   ./svc.sh install"
echo "   ./svc.sh start"
echo ""
echo "4. Runner 상태 확인:"
echo "   ./svc.sh status"
echo ""
echo "========================================"
echo " GitHub Secrets 설정 필요"
echo "========================================"
echo ""
echo "GitHub > Settings > Secrets and variables > Actions 에서 추가:"
echo ""
echo "  DATABASE_URL          = postgresql://postgres:xxxxx@172.30.1.72:5432/standup"
echo "  GMAIL_ADDRESS         = your_gmail@gmail.com"
echo "  GMAIL_APP_PASSWORD    = your_app_password"
echo "  REPORT_RECIPIENTS     = recipient@email.com"
echo "  GH_TOKEN              = your_github_token"
echo "  GITHUB_ORG            = bluevlad"
echo "  DAILY_REPORT_HOUR     = 17"
echo "  DAILY_REPORT_MINUTE   = 0"
echo "  WEEKLY_REPORT_HOUR    = 10"
echo "  WEEKLY_REPORT_MINUTE  = 0"
echo "  MONTHLY_REPORT_HOUR   = 11"
echo "  MONTHLY_REPORT_MINUTE = 0"
echo "  LOG_LEVEL             = INFO"
echo ""
echo "주의: GITHUB_TOKEN은 예약어이므로 GH_TOKEN으로 사용합니다."
