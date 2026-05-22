"""
보고서 조회 서비스

일/주/월 보고서의 자동 생성·발송 기능은 제거되었으며, 이 서비스는
대시보드의 보고서 아카이브 조회 용도로만 사용된다.
"""

from sqlalchemy.orm import Session

from ..models.report import Report, ReportType


class ReportService:
    """보고서 조회 서비스 (읽기 전용)"""

    def get_report(self, db: Session, report_id: int) -> Report | None:
        """보고서 조회"""
        return db.query(Report).filter(Report.id == report_id).first()

    def get_reports(
        self,
        db: Session,
        report_type: ReportType = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Report]:
        """보고서 목록 조회"""
        query = db.query(Report).order_by(Report.generated_at.desc())
        if report_type:
            query = query.filter(Report.report_type == report_type)
        return query.offset(offset).limit(limit).all()


# 싱글톤
_service = None


def get_report_service() -> ReportService:
    global _service
    if _service is None:
        _service = ReportService()
    return _service
