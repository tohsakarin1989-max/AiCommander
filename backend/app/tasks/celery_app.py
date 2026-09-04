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
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "expire-agent-approvals": {
            "task": "aicommander.agent.expire_approvals",
            "schedule": 900.0,
            "options": {"queue": settings.AGENT_REDIS_QUEUE},
        },
    },
)
