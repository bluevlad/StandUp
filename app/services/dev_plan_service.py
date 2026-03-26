"""
개발 플랜 서비스 - CRUD + 메트릭 산출
"""

import logging
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..core.config import now_kst
from ..models.dev_plan import (
    DevPlan, DevPlanItem, PlanStatus, PlanItemStatus, PlanItemPriority,
)

logger = logging.getLogger(__name__)

# 대상 프로젝트 목록
# - name: 프로젝트 표시명 / DevPlan.project_name 매칭키
# - repo: GitHub full path (owner/repo) - 링크 생성용
# - repo_name: WorkItem.github_repo 매칭키 (DB 저장 형식)
TARGET_PROJECTS = [
    {"name": "hopenvision", "repo": "bluevlad/hopenvision", "repo_name": "hopenvision"},
    {"name": "AllergyInsight", "repo": "bluevlad/AllergyInsight", "repo_name": "AllergyInsight"},
    {"name": "EduFit", "repo": "bluevlad/EduFit", "repo_name": "EduFit"},
    {"name": "NewsLetterPlatform", "repo": "bluevlad/NewsLetterPlatform", "repo_name": "NewsLetterPlatform"},
    {"name": "unmong-main", "repo": "bluevlad/unmong-main", "repo_name": "unmong-main"},
    {"name": "StandUp", "repo": "bluevlad/StandUp", "repo_name": "StandUp"},
    {"name": "Autonomous-QA-Agent", "repo": "bluevlad/Autonomous-QA-Agent", "repo_name": "Autonomous-QA-Agent"},
    {"name": "Auto-Tobe-Agent", "repo": "bluevlad/Auto-Tobe-Agent", "repo_name": "Auto-Tobe-Agent"},
]


class DevPlanService:
    """개발 플랜 서비스"""

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def get_plans(
        self,
        db: Session,
        project_name: str | None = None,
        status: PlanStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DevPlan]:
        query = (
            db.query(DevPlan)
            .options(joinedload(DevPlan.items))
            .order_by(DevPlan.project_name, DevPlan.updated_at.desc())
        )
        if project_name:
            query = query.filter(DevPlan.project_name == project_name)
        if status:
            query = query.filter(DevPlan.status == status)
        return query.offset(offset).limit(limit).all()

    def get_plan(self, db: Session, plan_id: int) -> DevPlan | None:
        return (
            db.query(DevPlan)
            .options(joinedload(DevPlan.items))
            .filter(DevPlan.id == plan_id)
            .first()
        )

    def create_plan(self, db: Session, data: dict) -> DevPlan:
        items_data = data.pop("items", [])
        plan = DevPlan(**data)
        db.add(plan)
        db.flush()

        for idx, item_data in enumerate(items_data):
            item_data["plan_id"] = plan.id
            item_data.setdefault("sort_order", idx)
            item = DevPlanItem(**item_data)
            db.add(item)

        db.commit()
        self.recalculate_metrics(db, plan.id)
        db.refresh(plan)
        return plan

    def update_plan(self, db: Session, plan_id: int, data: dict) -> DevPlan | None:
        plan = db.query(DevPlan).filter(DevPlan.id == plan_id).first()
        if not plan:
            return None

        for key, value in data.items():
            if value is not None and hasattr(plan, key):
                setattr(plan, key, value)

        db.commit()
        db.refresh(plan)
        return plan

    def delete_plan(self, db: Session, plan_id: int) -> bool:
        plan = db.query(DevPlan).filter(DevPlan.id == plan_id).first()
        if not plan:
            return False
        db.delete(plan)
        db.commit()
        return True

    # ------------------------------------------------------------------
    # Plan Items CRUD
    # ------------------------------------------------------------------

    def create_item(self, db: Session, plan_id: int, data: dict) -> DevPlanItem | None:
        plan = db.query(DevPlan).filter(DevPlan.id == plan_id).first()
        if not plan:
            return None

        data["plan_id"] = plan_id
        item = DevPlanItem(**data)
        db.add(item)
        db.commit()
        self.recalculate_metrics(db, plan_id)
        db.refresh(item)
        return item

    def update_item(self, db: Session, item_id: int, data: dict) -> DevPlanItem | None:
        item = db.query(DevPlanItem).filter(DevPlanItem.id == item_id).first()
        if not item:
            return None

        for key, value in data.items():
            if value is not None and hasattr(item, key):
                setattr(item, key, value)

        # 상태가 DONE으로 변경되면 completed_at, progress_pct 자동 설정
        if data.get("status") == PlanItemStatus.DONE:
            if not item.completed_at:
                item.completed_at = now_kst()
            item.progress_pct = 100.0

        db.commit()
        self.recalculate_metrics(db, item.plan_id)
        db.refresh(item)
        return item

    def delete_item(self, db: Session, item_id: int) -> bool:
        item = db.query(DevPlanItem).filter(DevPlanItem.id == item_id).first()
        if not item:
            return False
        plan_id = item.plan_id
        db.delete(item)
        db.commit()
        self.recalculate_metrics(db, plan_id)
        return True

    # ------------------------------------------------------------------
    # 메트릭 산출
    # ------------------------------------------------------------------

    def recalculate_metrics(self, db: Session, plan_id: int) -> None:
        """플랜의 진행률/완료율/품질평가율 재계산"""
        plan = (
            db.query(DevPlan)
            .options(joinedload(DevPlan.items))
            .filter(DevPlan.id == plan_id)
            .first()
        )
        if not plan or not plan.items:
            return

        items = plan.items
        total_weight = sum(i.weight for i in items)
        if total_weight == 0:
            return

        # 진행률: Σ(item.progress_pct × item.weight) / Σ(item.weight)
        progress = sum(i.progress_pct * i.weight for i in items) / total_weight

        # 완료율: Σ(DONE items weight) / Σ(total weight)
        done_weight = sum(i.weight for i in items if i.status == PlanItemStatus.DONE)
        completion = (done_weight / total_weight) * 100.0

        # 품질평가율:
        #   test_coverage  (0.3) : has_tests 비율
        #   review_score   (0.3) : has_review 비율
        #   bug_ratio      (0.2) : (1 - bug_count/total_items) × 100
        #   doc_score      (0.2) : has_docs 비율
        total_items = len(items)
        test_score = (sum(i.has_tests for i in items) / total_items) * 100
        review_score = (sum(i.has_review for i in items) / total_items) * 100
        total_bugs = sum(i.bug_count for i in items)
        bug_score = max(0, (1 - total_bugs / max(total_items, 1))) * 100
        doc_score = (sum(i.has_docs for i in items) / total_items) * 100

        quality = (
            test_score * 0.3
            + review_score * 0.3
            + bug_score * 0.2
            + doc_score * 0.2
        )

        plan.progress_pct = round(progress, 1)
        plan.completion_pct = round(completion, 1)
        plan.quality_score = round(quality, 1)

        db.commit()

    # ------------------------------------------------------------------
    # 대시보드용 프로젝트별 요약
    # ------------------------------------------------------------------

    def get_project_summary(self, db: Session) -> list[dict]:
        """대상 프로젝트별 종합 메트릭"""
        all_plans = (
            db.query(DevPlan)
            .options(joinedload(DevPlan.items))
            .filter(DevPlan.status.in_([PlanStatus.ACTIVE, PlanStatus.COMPLETED]))
            .order_by(DevPlan.project_name)
            .all()
        )

        # 프로젝트별 그룹핑
        project_map: dict[str, list[DevPlan]] = {}
        for proj in TARGET_PROJECTS:
            project_map[proj["name"]] = []

        for plan in all_plans:
            if plan.project_name in project_map:
                project_map[plan.project_name].append(plan)

        result = []
        for proj in TARGET_PROJECTS:
            name = proj["name"]
            plans = project_map.get(name, [])

            if not plans:
                result.append({
                    "project_name": name,
                    "github_repo": proj["repo"],
                    "plan_count": 0,
                    "total_items": 0,
                    "done_items": 0,
                    "progress_pct": 0.0,
                    "completion_pct": 0.0,
                    "quality_score": 0.0,
                    "active_plan_title": None,
                    "phases": [],
                })
                continue

            # 활성 플랜 우선
            active_plan = next(
                (p for p in plans if p.status == PlanStatus.ACTIVE), plans[0]
            )

            all_items = []
            for p in plans:
                all_items.extend(p.items)

            total_items = len(all_items)
            done_items = sum(1 for i in all_items if i.status == PlanItemStatus.DONE)
            total_weight = sum(i.weight for i in all_items) or 1

            progress = sum(i.progress_pct * i.weight for i in all_items) / total_weight
            done_weight = sum(i.weight for i in all_items if i.status == PlanItemStatus.DONE)
            completion = (done_weight / total_weight) * 100.0

            # 품질
            if total_items > 0:
                test_s = (sum(i.has_tests for i in all_items) / total_items) * 100
                review_s = (sum(i.has_review for i in all_items) / total_items) * 100
                bugs = sum(i.bug_count for i in all_items)
                bug_s = max(0, (1 - bugs / max(total_items, 1))) * 100
                doc_s = (sum(i.has_docs for i in all_items) / total_items) * 100
                quality = test_s * 0.3 + review_s * 0.3 + bug_s * 0.2 + doc_s * 0.2
            else:
                quality = 0.0

            # Phase별 메트릭 (활성 플랜 기준)
            phases = []
            if active_plan.items:
                phase_map: dict[int, dict] = {}
                for item in active_plan.items:
                    if item.phase not in phase_map:
                        phase_map[item.phase] = {
                            "phase": item.phase,
                            "phase_title": item.phase_title,
                            "total_items": 0,
                            "done_items": 0,
                            "total_weight": 0.0,
                            "done_weight": 0.0,
                            "progress_sum": 0.0,
                        }
                    pm = phase_map[item.phase]
                    pm["total_items"] += 1
                    pm["total_weight"] += item.weight
                    pm["progress_sum"] += item.progress_pct * item.weight
                    if item.status == PlanItemStatus.DONE:
                        pm["done_items"] += 1
                        pm["done_weight"] += item.weight

                for ph_num in sorted(phase_map.keys()):
                    pm = phase_map[ph_num]
                    tw = pm["total_weight"] or 1
                    phases.append({
                        "phase": pm["phase"],
                        "phase_title": pm["phase_title"],
                        "total_items": pm["total_items"],
                        "done_items": pm["done_items"],
                        "progress_pct": round(pm["progress_sum"] / tw, 1),
                        "completion_pct": round((pm["done_weight"] / tw) * 100, 1),
                    })

            result.append({
                "project_name": name,
                "github_repo": proj["repo"],
                "plan_count": len(plans),
                "total_items": total_items,
                "done_items": done_items,
                "progress_pct": round(progress, 1),
                "completion_pct": round(completion, 1),
                "quality_score": round(quality, 1),
                "active_plan_title": active_plan.title,
                "phases": phases,
            })

        return result

    def get_overall_metrics(self, db: Session) -> dict:
        """전체 프로젝트 종합 지표"""
        projects = self.get_project_summary(db)

        active_projects = [p for p in projects if p["plan_count"] > 0]
        total_projects = len(TARGET_PROJECTS)
        active_count = len(active_projects)

        if active_projects:
            avg_progress = sum(p["progress_pct"] for p in active_projects) / active_count
            avg_completion = sum(p["completion_pct"] for p in active_projects) / active_count
            avg_quality = sum(p["quality_score"] for p in active_projects) / active_count
            total_items = sum(p["total_items"] for p in active_projects)
            done_items = sum(p["done_items"] for p in active_projects)
        else:
            avg_progress = avg_completion = avg_quality = 0.0
            total_items = done_items = 0

        return {
            "total_projects": total_projects,
            "active_projects": active_count,
            "total_items": total_items,
            "done_items": done_items,
            "avg_progress": round(avg_progress, 1),
            "avg_completion": round(avg_completion, 1),
            "avg_quality": round(avg_quality, 1),
        }


# 싱글톤
_service = None


def get_dev_plan_service() -> DevPlanService:
    global _service
    if _service is None:
        _service = DevPlanService()
    return _service
