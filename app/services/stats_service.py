"""
통계 서비스 - 보고서 및 업무 항목 통계 쿼리
"""

from datetime import datetime, timedelta

from sqlalchemy import func, case, extract
from sqlalchemy.orm import Session

from ..core.config import now_kst
from ..models.issue import WorkItem, ItemCategory, ItemStatus
from ..models.report import Report, ReportItem, ReportType, ReportStatus


class StatsService:
    """통계 쿼리 서비스"""

    def get_summary(
        self,
        db: Session,
        period_type: str = "daily",
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict:
        """기간별 요약 통계"""
        now = now_kst()

        if date_from is None or date_to is None:
            date_from, date_to = self._default_range(period_type, now)

        query = db.query(WorkItem).filter(
            WorkItem.updated_at >= date_from,
            WorkItem.updated_at <= date_to,
        )
        items = query.all()

        total = len(items)
        by_category = {}
        by_status = {}
        for item in items:
            by_category[item.category.value] = by_category.get(item.category.value, 0) + 1
            by_status[item.status.value] = by_status.get(item.status.value, 0) + 1

        resolved = by_status.get("resolved", 0) + by_status.get("closed", 0)
        completion_rate = round((resolved / total * 100), 1) if total > 0 else 0.0

        # 프로젝트별 건수
        projects = {}
        for item in items:
            projects[item.github_repo] = projects.get(item.github_repo, 0) + 1

        return {
            "period_type": period_type,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "total_items": total,
            "by_category": by_category,
            "by_status": by_status,
            "completion_rate": completion_rate,
            "project_count": len(projects),
            "projects": dict(sorted(projects.items(), key=lambda x: x[1], reverse=True)),
        }

    def get_trend(
        self,
        db: Session,
        period_type: str = "daily",
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[dict]:
        """기간별 트렌드 데이터 (차트용)"""
        now = now_kst()

        if date_from is None or date_to is None:
            date_from, date_to = self._default_range(period_type, now)

        items = (
            db.query(WorkItem)
            .filter(
                WorkItem.updated_at >= date_from,
                WorkItem.updated_at <= date_to,
            )
            .all()
        )

        if period_type == "monthly":
            return self._group_by_month(items, date_from, date_to)
        elif period_type == "weekly":
            return self._group_by_week(items, date_from, date_to)
        else:
            return self._group_by_day(items, date_from, date_to)

    def get_report_stats(
        self,
        db: Session,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict:
        """보고서 발송 통계"""
        now = now_kst()
        if date_from is None:
            date_from = now - timedelta(days=30)
        if date_to is None:
            date_to = now

        reports = (
            db.query(Report)
            .filter(
                Report.generated_at >= date_from,
                Report.generated_at <= date_to,
            )
            .all()
        )

        by_type = {}
        by_status = {}
        for r in reports:
            by_type[r.report_type.value] = by_type.get(r.report_type.value, 0) + 1
            by_status[r.status.value] = by_status.get(r.status.value, 0) + 1

        total = len(reports)
        sent = by_status.get("sent", 0) + by_status.get("partial_sent", 0)
        success_rate = round((sent / total * 100), 1) if total > 0 else 0.0

        return {
            "total_reports": total,
            "by_type": by_type,
            "by_status": by_status,
            "success_rate": success_rate,
        }

    def _default_range(self, period_type: str, now: datetime) -> tuple[datetime, datetime]:
        """period_type에 따른 기본 날짜 범위"""
        if period_type == "monthly":
            date_from = (now - timedelta(days=365)).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
        elif period_type == "weekly":
            date_from = (now - timedelta(days=90)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        else:  # daily
            date_from = (now - timedelta(days=30)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        return date_from, now

    def _group_by_day(self, items: list[WorkItem], date_from: datetime, date_to: datetime) -> list[dict]:
        """일별 그룹핑"""
        buckets = {}
        current = date_from.replace(hour=0, minute=0, second=0, microsecond=0)
        end = date_to.replace(hour=0, minute=0, second=0, microsecond=0)
        while current <= end:
            buckets[current.strftime("%Y-%m-%d")] = self._empty_bucket()
            current += timedelta(days=1)

        for item in items:
            key = item.updated_at.strftime("%Y-%m-%d")
            if key in buckets:
                self._count_item(buckets[key], item)

        return [{"date": k, **v} for k, v in buckets.items()]

    def _group_by_week(self, items: list[WorkItem], date_from: datetime, date_to: datetime) -> list[dict]:
        """주별 그룹핑"""
        buckets = {}
        current = date_from - timedelta(days=date_from.weekday())
        current = current.replace(hour=0, minute=0, second=0, microsecond=0)
        while current <= date_to:
            key = current.strftime("%Y-W%W")
            buckets[key] = {**self._empty_bucket(), "week_start": current.strftime("%m/%d")}
            current += timedelta(weeks=1)

        for item in items:
            dt = item.updated_at
            week_start = dt - timedelta(days=dt.weekday())
            key = week_start.strftime("%Y-W%W")
            if key in buckets:
                self._count_item(buckets[key], item)

        return [{"date": k, **v} for k, v in buckets.items()]

    def _group_by_month(self, items: list[WorkItem], date_from: datetime, date_to: datetime) -> list[dict]:
        """월별 그룹핑"""
        buckets = {}
        current = date_from.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        while current <= date_to:
            key = current.strftime("%Y-%m")
            buckets[key] = self._empty_bucket()
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

        for item in items:
            key = item.updated_at.strftime("%Y-%m")
            if key in buckets:
                self._count_item(buckets[key], item)

        return [{"date": k, **v} for k, v in buckets.items()]

    def _empty_bucket(self) -> dict:
        return {
            "planned": 0,
            "required": 0,
            "in_progress": 0,
            "resolved": 0,
            "open": 0,
            "total": 0,
        }

    def _count_item(self, bucket: dict, item: WorkItem):
        bucket["total"] += 1
        bucket[item.category.value] = bucket.get(item.category.value, 0) + 1
        if item.status in (ItemStatus.RESOLVED, ItemStatus.CLOSED):
            bucket["resolved"] += 1
        elif item.status == ItemStatus.OPEN:
            bucket["open"] += 1


# 싱글톤
_service = None


def get_stats_service() -> StatsService:
    global _service
    if _service is None:
        _service = StatsService()
    return _service
