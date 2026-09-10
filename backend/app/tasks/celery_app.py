from celery import Celery
from app.config import settings

celery_app = Celery(
    "aicommander",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.meeting_tasks",
        "app.tasks.preprocess_tasks",
        "app.tasks.chain_tasks",
        "app.tasks.agent_tasks",
        "app.tasks.case_pipeline_tasks",
        "app.tasks.case_insight_tasks",
        "app.tasks.case_result_tasks",
        "app.tasks.deployment_advisor_tasks",
        "app.tasks.map_package_tasks",
        "app.tasks.intelligent_query_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "process-intelligent-query": {
            "task": "aicommander.queries.process_next",
            "schedule": 5.0,
            "options": {"queue": settings.AGENT_REDIS_QUEUE, "expires": 5},
        },
        "process-map-package-import": {
            "task": "aicommander.maps.process_import",
            "schedule": 30.0,
            "options": {"queue": "map_build", "expires": 30},
        },
        "expire-agent-approvals": {
            "task": "aicommander.agent.expire_approvals",
            "schedule": 900.0,
            "options": {"queue": settings.AGENT_REDIS_QUEUE},
        },
        "process-case-pipeline": {
            "task": "aicommander.case_pipeline.process_pending",
            "schedule": 5.0,
        },
        "process-case-insights": {
            "task": "aicommander.case_insights.process_pending",
            "schedule": 5.0,
        },
        "reconcile-current-case-insights": {
            "task": "aicommander.case_insights.reconcile_current_pairs",
            "schedule": 60.0,
        },
        "reconcile-case-results": {
            "task": "aicommander.case_results.reconcile",
            "schedule": 60.0,
            "options": {"expires": 60},
        },
        "generate-daily-situation-briefs": {
            "task": "aicommander.deployment_advisor.generate_daily",
            "schedule": 3600.0,
        },
        "generate-weekly-situation-briefs": {
            "task": "aicommander.deployment_advisor.generate_weekly",
            "schedule": 21600.0,
        },
    },
)
