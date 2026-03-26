"""
8개 대상 프로젝트의 초기 개발 플랜 시드 데이터
실행: python -m scripts.seed_dev_plans
"""

import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal
from app.models.dev_plan import (
    DevPlan, DevPlanItem, PlanStatus, PlanItemStatus, PlanItemPriority,
)


SEED_DATA = [
    {
        "project_name": "hopenvision",
        "github_repo": "bluevlad/hopenvision",
        "title": "hopenvision 플랫폼 구축",
        "description": "오픈소스 비전 AI 플랫폼 핵심 기능 구현",
        "status": PlanStatus.ACTIVE,
        "total_phases": 3,
        "current_phase": 1,
        "items": [
            {"phase": 1, "phase_title": "기반 구조", "title": "프로젝트 초기 구조 설계", "priority": PlanItemPriority.P0, "weight": 2.0, "status": PlanItemStatus.DONE, "progress_pct": 100, "has_docs": 1},
            {"phase": 1, "phase_title": "기반 구조", "title": "CI/CD 파이프라인 구성", "priority": PlanItemPriority.P1, "weight": 1.5, "status": PlanItemStatus.DONE, "progress_pct": 100, "has_tests": 1},
            {"phase": 1, "phase_title": "기반 구조", "title": "개발환경 Docker 구성", "priority": PlanItemPriority.P1, "weight": 1.0, "status": PlanItemStatus.IN_PROGRESS, "progress_pct": 60},
            {"phase": 2, "phase_title": "핵심 기능", "title": "이미지 분석 API 개발", "priority": PlanItemPriority.P0, "weight": 3.0, "status": PlanItemStatus.TODO, "progress_pct": 0},
            {"phase": 2, "phase_title": "핵심 기능", "title": "모델 학습 파이프라인", "priority": PlanItemPriority.P1, "weight": 2.5, "status": PlanItemStatus.TODO, "progress_pct": 0},
            {"phase": 3, "phase_title": "UI/배포", "title": "웹 대시보드 UI", "priority": PlanItemPriority.P2, "weight": 2.0, "status": PlanItemStatus.TODO, "progress_pct": 0},
            {"phase": 3, "phase_title": "UI/배포", "title": "운영 배포 및 모니터링", "priority": PlanItemPriority.P1, "weight": 1.5, "status": PlanItemStatus.TODO, "progress_pct": 0},
        ],
    },
    {
        "project_name": "AllergyInsight",
        "github_repo": "bluevlad/AllergyInsight",
        "title": "AllergyInsight 서비스 개발",
        "description": "알레르기 정보 분석 및 안전 식품 추천 서비스",
        "status": PlanStatus.ACTIVE,
        "total_phases": 3,
        "current_phase": 2,
        "items": [
            {"phase": 1, "phase_title": "데이터 수집", "title": "식품 알레르기 DB 스키마 설계", "priority": PlanItemPriority.P0, "weight": 2.0, "status": PlanItemStatus.DONE, "progress_pct": 100, "has_tests": 1, "has_review": 1, "has_docs": 1},
            {"phase": 1, "phase_title": "데이터 수집", "title": "공공데이터 API 연동", "priority": PlanItemPriority.P0, "weight": 2.5, "status": PlanItemStatus.DONE, "progress_pct": 100, "has_tests": 1, "has_review": 1},
            {"phase": 1, "phase_title": "데이터 수집", "title": "데이터 정제 파이프라인", "priority": PlanItemPriority.P1, "weight": 1.5, "status": PlanItemStatus.DONE, "progress_pct": 100, "has_tests": 1},
            {"phase": 2, "phase_title": "분석 엔진", "title": "알레르기 성분 분석 엔진", "priority": PlanItemPriority.P0, "weight": 3.0, "status": PlanItemStatus.IN_PROGRESS, "progress_pct": 70, "has_tests": 1},
            {"phase": 2, "phase_title": "분석 엔진", "title": "식품 안전도 스코어링", "priority": PlanItemPriority.P1, "weight": 2.0, "status": PlanItemStatus.IN_PROGRESS, "progress_pct": 40},
            {"phase": 2, "phase_title": "분석 엔진", "title": "사용자 프로필 기반 추천", "priority": PlanItemPriority.P1, "weight": 2.0, "status": PlanItemStatus.TODO, "progress_pct": 0},
            {"phase": 3, "phase_title": "서비스 런칭", "title": "모바일 앱 UI", "priority": PlanItemPriority.P1, "weight": 2.5, "status": PlanItemStatus.TODO, "progress_pct": 0},
            {"phase": 3, "phase_title": "서비스 런칭", "title": "베타 테스트 및 피드백 반영", "priority": PlanItemPriority.P2, "weight": 1.5, "status": PlanItemStatus.TODO, "progress_pct": 0},
        ],
    },
    {
        "project_name": "EduFit",
        "github_repo": "bluevlad/EduFit",
        "title": "EduFit 학습 관리 플랫폼",
        "description": "개인 맞춤형 학습 관리 및 진도 추적 시스템",
        "status": PlanStatus.ACTIVE,
        "total_phases": 3,
        "current_phase": 1,
        "items": [
            {"phase": 1, "phase_title": "기반 설계", "title": "학습 모델 DB 설계", "priority": PlanItemPriority.P0, "weight": 2.0, "status": PlanItemStatus.DONE, "progress_pct": 100, "has_tests": 1, "has_docs": 1},
            {"phase": 1, "phase_title": "기반 설계", "title": "사용자 인증/권한 시스템", "priority": PlanItemPriority.P0, "weight": 1.5, "status": PlanItemStatus.IN_PROGRESS, "progress_pct": 50},
            {"phase": 1, "phase_title": "기반 설계", "title": "REST API 기본 구조", "priority": PlanItemPriority.P1, "weight": 1.5, "status": PlanItemStatus.IN_PROGRESS, "progress_pct": 30},
            {"phase": 2, "phase_title": "학습 엔진", "title": "학습 진도 추적 엔진", "priority": PlanItemPriority.P0, "weight": 3.0, "status": PlanItemStatus.TODO, "progress_pct": 0},
            {"phase": 2, "phase_title": "학습 엔진", "title": "맞춤 학습 추천 알고리즘", "priority": PlanItemPriority.P1, "weight": 2.5, "status": PlanItemStatus.TODO, "progress_pct": 0},
            {"phase": 3, "phase_title": "프론트엔드", "title": "학습 대시보드 UI", "priority": PlanItemPriority.P1, "weight": 2.0, "status": PlanItemStatus.TODO, "progress_pct": 0},
            {"phase": 3, "phase_title": "프론트엔드", "title": "모바일 반응형 적용", "priority": PlanItemPriority.P2, "weight": 1.0, "status": PlanItemStatus.TODO, "progress_pct": 0},
        ],
    },
    {
        "project_name": "NewsLetterPlatform",
        "github_repo": "bluevlad/NewsLetterPlatform",
        "title": "NewsLetter 자동화 플랫폼",
        "description": "뉴스레터 작성/발송/구독 관리 자동화 시스템",
        "status": PlanStatus.ACTIVE,
        "total_phases": 3,
        "current_phase": 2,
        "items": [
            {"phase": 1, "phase_title": "기반 구축", "title": "이메일 발송 엔진", "priority": PlanItemPriority.P0, "weight": 2.0, "status": PlanItemStatus.DONE, "progress_pct": 100, "has_tests": 1, "has_review": 1, "has_docs": 1},
            {"phase": 1, "phase_title": "기반 구축", "title": "구독자 관리 시스템", "priority": PlanItemPriority.P0, "weight": 1.5, "status": PlanItemStatus.DONE, "progress_pct": 100, "has_tests": 1, "has_review": 1},
            {"phase": 1, "phase_title": "기반 구축", "title": "템플릿 엔진 구현", "priority": PlanItemPriority.P1, "weight": 1.5, "status": PlanItemStatus.DONE, "progress_pct": 100, "has_tests": 1},
            {"phase": 2, "phase_title": "자동화", "title": "콘텐츠 자동 큐레이션", "priority": PlanItemPriority.P0, "weight": 3.0, "status": PlanItemStatus.IN_PROGRESS, "progress_pct": 60, "has_tests": 1},
            {"phase": 2, "phase_title": "자동화", "title": "발송 스케줄링 시스템", "priority": PlanItemPriority.P1, "weight": 2.0, "status": PlanItemStatus.REVIEW, "progress_pct": 90, "has_tests": 1, "has_review": 1},
            {"phase": 2, "phase_title": "자동화", "title": "A/B 테스트 기능", "priority": PlanItemPriority.P2, "weight": 1.5, "status": PlanItemStatus.TODO, "progress_pct": 0},
            {"phase": 3, "phase_title": "분석/최적화", "title": "오픈율/클릭율 분석 대시보드", "priority": PlanItemPriority.P1, "weight": 2.0, "status": PlanItemStatus.TODO, "progress_pct": 0},
            {"phase": 3, "phase_title": "분석/최적화", "title": "구독자 세그먼트 분석", "priority": PlanItemPriority.P2, "weight": 1.5, "status": PlanItemStatus.TODO, "progress_pct": 0},
        ],
    },
    {
        "project_name": "unmong-main",
        "github_repo": "bluevlad/unmong-main",
        "title": "운몽 메인 서비스 개발",
        "description": "운몽 핵심 서비스 아키텍처 구축 및 기능 개발",
        "status": PlanStatus.ACTIVE,
        "total_phases": 3,
        "current_phase": 1,
        "items": [
            {"phase": 1, "phase_title": "아키텍처", "title": "마이크로서비스 구조 설계", "priority": PlanItemPriority.P0, "weight": 2.5, "status": PlanItemStatus.DONE, "progress_pct": 100, "has_docs": 1, "has_review": 1},
            {"phase": 1, "phase_title": "아키텍처", "title": "API Gateway 구축", "priority": PlanItemPriority.P0, "weight": 2.0, "status": PlanItemStatus.IN_PROGRESS, "progress_pct": 70},
            {"phase": 1, "phase_title": "아키텍처", "title": "인증/인가 서비스", "priority": PlanItemPriority.P0, "weight": 2.0, "status": PlanItemStatus.IN_PROGRESS, "progress_pct": 40},
            {"phase": 2, "phase_title": "핵심 서비스", "title": "사용자 관리 서비스", "priority": PlanItemPriority.P1, "weight": 2.0, "status": PlanItemStatus.TODO, "progress_pct": 0},
            {"phase": 2, "phase_title": "핵심 서비스", "title": "콘텐츠 관리 서비스", "priority": PlanItemPriority.P1, "weight": 2.5, "status": PlanItemStatus.TODO, "progress_pct": 0},
            {"phase": 3, "phase_title": "운영", "title": "모니터링/로깅 시스템", "priority": PlanItemPriority.P1, "weight": 1.5, "status": PlanItemStatus.TODO, "progress_pct": 0},
            {"phase": 3, "phase_title": "운영", "title": "운영 배포 자동화", "priority": PlanItemPriority.P1, "weight": 1.5, "status": PlanItemStatus.TODO, "progress_pct": 0},
        ],
    },
    {
        "project_name": "StandUp",
        "github_repo": "bluevlad/StandUp",
        "title": "StandUp 업무관리 자동화 고도화",
        "description": "업무보고 자동화 시스템 - 메트릭 기반 보고 체계 구축",
        "status": PlanStatus.ACTIVE,
        "total_phases": 3,
        "current_phase": 2,
        "items": [
            {"phase": 1, "phase_title": "기반 시스템", "title": "GitHub Issues 자동 수집 (QA-Agent)", "priority": PlanItemPriority.P0, "weight": 2.0, "status": PlanItemStatus.DONE, "progress_pct": 100, "has_tests": 1, "has_review": 1, "has_docs": 1},
            {"phase": 1, "phase_title": "기반 시스템", "title": "Commit 기반 진행 추적 (Tobe-Agent)", "priority": PlanItemPriority.P0, "weight": 2.0, "status": PlanItemStatus.DONE, "progress_pct": 100, "has_tests": 1, "has_review": 1, "has_docs": 1},
            {"phase": 1, "phase_title": "기반 시스템", "title": "보고서 자동 생성/발송 (Report-Agent)", "priority": PlanItemPriority.P0, "weight": 2.0, "status": PlanItemStatus.DONE, "progress_pct": 100, "has_tests": 1, "has_review": 1, "has_docs": 1},
            {"phase": 1, "phase_title": "기반 시스템", "title": "대시보드 웹 UI", "priority": PlanItemPriority.P1, "weight": 1.5, "status": PlanItemStatus.DONE, "progress_pct": 100, "has_tests": 1, "has_docs": 1},
            {"phase": 2, "phase_title": "메트릭 고도화", "title": "DevPlan 모델 및 메트릭 엔진", "priority": PlanItemPriority.P0, "weight": 3.0, "status": PlanItemStatus.IN_PROGRESS, "progress_pct": 80, "has_tests": 1},
            {"phase": 2, "phase_title": "메트릭 고도화", "title": "프로젝트별 진행률/완료율/품질 대시보드", "priority": PlanItemPriority.P0, "weight": 2.5, "status": PlanItemStatus.IN_PROGRESS, "progress_pct": 70},
            {"phase": 2, "phase_title": "메트릭 고도화", "title": "PR/Review 기반 품질 자동 산출", "priority": PlanItemPriority.P1, "weight": 2.0, "status": PlanItemStatus.TODO, "progress_pct": 0},
            {"phase": 3, "phase_title": "자동화 확장", "title": "Plan-Agent (외부 repo 플랜 동기화)", "priority": PlanItemPriority.P1, "weight": 2.0, "status": PlanItemStatus.TODO, "progress_pct": 0},
            {"phase": 3, "phase_title": "자동화 확장", "title": "정체 감지 알림 시스템", "priority": PlanItemPriority.P2, "weight": 1.0, "status": PlanItemStatus.TODO, "progress_pct": 0},
        ],
    },
    {
        "project_name": "Autonomous-QA-Agent",
        "github_repo": "bluevlad/Autonomous-QA-Agent",
        "title": "자율형 QA 에이전트 개발",
        "description": "AI 기반 자율 품질 보증 에이전트 시스템",
        "status": PlanStatus.ACTIVE,
        "total_phases": 3,
        "current_phase": 1,
        "items": [
            {"phase": 1, "phase_title": "에이전트 코어", "title": "에이전트 프레임워크 설계", "priority": PlanItemPriority.P0, "weight": 2.5, "status": PlanItemStatus.DONE, "progress_pct": 100, "has_docs": 1, "has_review": 1},
            {"phase": 1, "phase_title": "에이전트 코어", "title": "테스트 자동 생성 엔진", "priority": PlanItemPriority.P0, "weight": 3.0, "status": PlanItemStatus.IN_PROGRESS, "progress_pct": 50, "has_tests": 1},
            {"phase": 1, "phase_title": "에이전트 코어", "title": "코드 분석 모듈", "priority": PlanItemPriority.P1, "weight": 2.0, "status": PlanItemStatus.IN_PROGRESS, "progress_pct": 30},
            {"phase": 2, "phase_title": "자율 실행", "title": "테스트 실행 및 결과 분석", "priority": PlanItemPriority.P0, "weight": 2.5, "status": PlanItemStatus.TODO, "progress_pct": 0},
            {"phase": 2, "phase_title": "자율 실행", "title": "버그 리포트 자동 생성", "priority": PlanItemPriority.P1, "weight": 2.0, "status": PlanItemStatus.TODO, "progress_pct": 0},
            {"phase": 3, "phase_title": "통합", "title": "CI/CD 파이프라인 통합", "priority": PlanItemPriority.P1, "weight": 1.5, "status": PlanItemStatus.TODO, "progress_pct": 0},
            {"phase": 3, "phase_title": "통합", "title": "리포팅 대시보드", "priority": PlanItemPriority.P2, "weight": 1.0, "status": PlanItemStatus.TODO, "progress_pct": 0},
        ],
    },
    {
        "project_name": "Auto-Tobe-Agent",
        "github_repo": "bluevlad/Auto-Tobe-Agent",
        "title": "자동 진행 추적 에이전트",
        "description": "Git 활동 기반 프로젝트 진행 자동 추적 및 보고 에이전트",
        "status": PlanStatus.ACTIVE,
        "total_phases": 2,
        "current_phase": 1,
        "items": [
            {"phase": 1, "phase_title": "수집/분석", "title": "Git 활동 수집 모듈", "priority": PlanItemPriority.P0, "weight": 2.0, "status": PlanItemStatus.DONE, "progress_pct": 100, "has_tests": 1, "has_review": 1, "has_docs": 1},
            {"phase": 1, "phase_title": "수집/분석", "title": "커밋 메시지 분석 엔진", "priority": PlanItemPriority.P0, "weight": 2.5, "status": PlanItemStatus.DONE, "progress_pct": 100, "has_tests": 1, "has_review": 1},
            {"phase": 1, "phase_title": "수집/분석", "title": "이슈-커밋 매핑 로직", "priority": PlanItemPriority.P1, "weight": 1.5, "status": PlanItemStatus.DONE, "progress_pct": 100, "has_tests": 1},
            {"phase": 1, "phase_title": "수집/분석", "title": "진행률 자동 추정 알고리즘", "priority": PlanItemPriority.P0, "weight": 2.0, "status": PlanItemStatus.IN_PROGRESS, "progress_pct": 60},
            {"phase": 2, "phase_title": "보고/통합", "title": "자동 보고서 생성", "priority": PlanItemPriority.P1, "weight": 2.0, "status": PlanItemStatus.TODO, "progress_pct": 0},
            {"phase": 2, "phase_title": "보고/통합", "title": "StandUp 시스템 연동", "priority": PlanItemPriority.P1, "weight": 1.5, "status": PlanItemStatus.TODO, "progress_pct": 0},
        ],
    },
]


def seed():
    db = SessionLocal()
    try:
        # 기존 데이터 확인
        existing = db.query(DevPlan).count()
        if existing > 0:
            print(f"이미 {existing}개의 플랜이 존재합니다. 시드를 건너뜁니다.")
            print("초기화하려면 dev_plan_items, dev_plans 테이블을 비운 후 다시 실행하세요.")
            return

        for plan_data in SEED_DATA:
            items_data = plan_data.pop("items")
            plan = DevPlan(**plan_data)
            db.add(plan)
            db.flush()

            for idx, item_data in enumerate(items_data):
                item_data["plan_id"] = plan.id
                item_data["sort_order"] = idx
                # DONE 상태 항목은 completed_at 설정
                if item_data.get("status") == PlanItemStatus.DONE:
                    from datetime import datetime
                    item_data["completed_at"] = datetime.now()
                item = DevPlanItem(**item_data)
                db.add(item)

            db.flush()

        db.commit()
        print(f"{len(SEED_DATA)}개 프로젝트의 개발 플랜이 생성되었습니다.")

        # 메트릭 재계산
        from app.services.dev_plan_service import get_dev_plan_service
        service = get_dev_plan_service()
        plans = db.query(DevPlan).all()
        for plan in plans:
            service.recalculate_metrics(db, plan.id)
        print("메트릭 재계산 완료")

    except Exception as e:
        db.rollback()
        print(f"시드 실패: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
