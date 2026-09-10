"""按日、按周生成厂区态势简报；输入未变化时服务层保持幂等。"""
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models.map_foundation import OperationalArea
from app.services.deployment_advisor_service import DeploymentAdvisorService
from app.tasks.celery_app import celery_app


def _generate(period_type: str) -> dict:
    db = SessionLocal()
    generated = 0
    replayed = 0
    try:
        area_ids = [
            item[0]
            for item in db.query(OperationalArea.id)
            .filter(OperationalArea.status == "active")
            .all()
        ]
        for area_id in area_ids:
            _, replay = DeploymentAdvisorService.generate_brief(
                db,
                operational_area_id=area_id,
                period_type=period_type,
                as_of=datetime.now(timezone.utc),
            )
            if replay:
                replayed += 1
            else:
                generated += 1
        return {"generated": generated, "replayed": replayed, "areas": len(area_ids)}
    finally:
        db.close()


@celery_app.task(name="aicommander.deployment_advisor.generate_daily")
def generate_daily_briefs() -> dict:
    return _generate("daily")


@celery_app.task(name="aicommander.deployment_advisor.generate_weekly")
def generate_weekly_briefs() -> dict:
    return _generate("weekly")
