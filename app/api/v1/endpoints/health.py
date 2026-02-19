"""
헬스체크 엔드포인트
"""

from fastapi import APIRouter

from ....core.scheduler import scheduler

router = APIRouter()


@router.get("/health")
def health_check():
    """서비스 상태 확인"""
    jobs = scheduler.get_jobs() if scheduler.running else []
    return {
        "status": "ok",
        "service": "StandUp",
        "scheduler": {
            "running": scheduler.running,
            "jobs": [
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run": str(job.next_run_time) if job.next_run_time else None,
                }
                for job in jobs
            ],
        },
    }
