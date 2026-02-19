"""
이메일 발송 테스트 스크립트
사용: python -m scripts.test_email
"""

import sys
import os
import logging

# 프로젝트 루트를 PYTHONPATH에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    from app.services.email_service import EmailService
    from app.core.config import settings

    logger.info("=== StandUp 이메일 발송 테스트 ===")
    logger.info(f"발신자: {settings.gmail_address}")
    logger.info(f"수신자: {settings.recipient_list}")

    service = EmailService()

    if not service.is_configured:
        logger.error("Gmail 설정이 완료되지 않았습니다.")
        logger.error(".env 파일에 GMAIL_ADDRESS와 GMAIL_APP_PASSWORD를 설정하세요.")
        sys.exit(1)

    # 테스트 HTML 로드
    template_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "templates", "test_email.html"
    )

    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # 발송
    recipient = settings.gmail_address  # 자신에게 테스트 발송
    result = service.send(
        recipient=recipient,
        subject="[StandUp 테스트] 이메일 발송 테스트",
        html_content=html_content,
    )

    if result.success:
        logger.info(f"테스트 이메일 발송 성공! → {recipient}")
    else:
        logger.error(f"테스트 이메일 발송 실패: {result.error_message}")
        sys.exit(1)


if __name__ == "__main__":
    main()
