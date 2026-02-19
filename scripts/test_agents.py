"""
Agent 통합 테스트 스크립트 (SQLite 사용)
Usage: python -m scripts.test_agents
"""

import sys
import os
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# SQLite로 테스트하기 위해 환경변수 먼저 설정
os.environ["DATABASE_URL"] = "sqlite:///./test_standup.db"

from dotenv import load_dotenv
load_dotenv(override=False)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    from app.core.database import engine, Base
    from app.core.config import settings
    from app.agents.qa_agent import QAAgent
    from app.agents.tobe_agent import TobeAgent

    # DB 테이블 생성 (SQLite)
    logger.info("=== Agent 통합 테스트 시작 ===")
    logger.info(f"DB: {settings.database_url}")

    from app.models import WorkItem, Report, ReportItem  # noqa: F401
    Base.metadata.create_all(bind=engine)
    logger.info("DB 테이블 생성 완료")

    # QA-Agent 실행
    logger.info("\n--- QA-Agent 실행 ---")
    qa = QAAgent()
    qa.run()

    # 결과 확인
    from app.core.database import SessionLocal
    from app.models.issue import WorkItem, ItemCategory

    db = SessionLocal()
    try:
        total = db.query(WorkItem).count()
        planned = db.query(WorkItem).filter(WorkItem.category == ItemCategory.PLANNED).count()
        required = db.query(WorkItem).filter(WorkItem.category == ItemCategory.REQUIRED).count()
        in_progress = db.query(WorkItem).filter(WorkItem.category == ItemCategory.IN_PROGRESS).count()

        logger.info(f"\nQA-Agent 결과:")
        logger.info(f"  총 항목: {total}건")
        logger.info(f"  예정사항: {planned}건")
        logger.info(f"  요구사항: {required}건")
        logger.info(f"  진행사항: {in_progress}건")

        # 상위 5건 출력
        items = db.query(WorkItem).order_by(WorkItem.created_at.desc()).limit(10).all()
        logger.info(f"\n최근 등록 항목 (상위 10건):")
        for item in items:
            logger.info(
                f"  [{item.category.value:12s}] {item.github_repo:30s} "
                f"#{item.github_issue_number or '-':>4} {item.title[:50]}"
            )

        # Tobe-Agent 실행
        logger.info("\n--- Tobe-Agent 실행 ---")
        tobe = TobeAgent()
        tobe.run()

        # 결과 재확인
        total_after = db.query(WorkItem).count()
        in_progress_after = db.query(WorkItem).filter(
            WorkItem.category == ItemCategory.IN_PROGRESS
        ).count()

        logger.info(f"\nTobe-Agent 결과:")
        logger.info(f"  총 항목: {total_after}건 (QA 이후 +{total_after - total}건)")
        logger.info(f"  진행사항: {in_progress_after}건")

        logger.info("\n=== Agent 통합 테스트 완료 ===")

    finally:
        db.close()

    # 테스트 DB 파일 정리
    engine.dispose()
    try:
        if os.path.exists("./test_standup.db"):
            os.remove("./test_standup.db")
            logger.info("테스트 DB 파일 삭제 완료")
    except PermissionError:
        logger.warning("테스트 DB 파일 삭제 실패 (잠금). 수동 삭제 필요: test_standup.db")


if __name__ == "__main__":
    main()
