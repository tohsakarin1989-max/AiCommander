from celery import Celery
from app.config import settings
from app.services.runtime_capabilities import query_creation_enabled

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
        "app.tasks.case_history_tasks",
        "app.tasks.case_insight_tasks",
        "app.tasks.case_result_tasks",
        "app.tasks.case_road_tasks",
        "app.tasks.deployment_advisor_tasks",
        "app.tasks.map_package_tasks",
        "app.tasks.intelligent_query_tasks",
        "app.tasks.analysis_topic_tasks",
        "app.tasks.facility_summary_tasks",
        "app.tasks.result_catalog_tasks",
        "app.tasks.case_draft_tasks",
        "app.tasks.map_ingest_tasks",
    ],
)


def build_beat_schedule(config):
    """Build once at process startup; restart Beat after changing feature flags."""
    schedule = {
        "process-map-ledger": {
            "task": "aicommander.map_ledgers.process_next",
            "schedule": 10.0,
            "options": {"queue": "map_build", "expires": 10},
        },
        "expire-case-drafts": {
            "task": "aicommander.case_drafts.expire",
            "schedule": 3600.0,
            "options": {"expires": 3600},
        },
        "expire-intelligent-queries": {
            "task": "aicommander.queries.expire",
            "schedule": 60.0,
            "options": {"expires": 60},
        },
        "process-case-chain": {
            "task": "aicommander.chain.process_pending",
            "schedule": 10.0,
            "options": {"expires": 10},
        },
        "reconcile-facility-catalog": {
            "task": "aicommander.facilities.reconcile",
            "schedule": 60.0,
            "options": {"expires": 60},
        },
        "reconcile-material-catalog": {
            "task": "aicommander.materials.reconcile_catalog",
            "schedule": 60.0,
            "options": {"expires": 60},
        },
        "process-analysis-topic": {
            "task": "aicommander.topics.process_next",
            "schedule": 15.0,
            # Saved topics are deterministic daily business, not Agent Lab.
            "options": {"expires": 15},
        },
        "reconcile-case-history-index": {
            "task": "aicommander.case_history.reconcile",
            "schedule": 15.0,
            "options": {"expires": 15},
        },
        "process-case-road-comparison": {
            "task": "aicommander.case_roads.process_next",
            "schedule": 10.0,
            "options": {"queue": "road_analysis", "expires": 10},
        },
        "reconcile-facility-algorithm": {
            "task": "aicommander.case_roads.reconcile_algorithm",
            "schedule": 300.0,
            "options": {"queue": "road_analysis", "expires": 300},
        },
        "reconcile-facility-dependencies": {
            "task": "aicommander.case_roads.reconcile_dependencies",
            "schedule": 60.0,
            "options": {"queue": "road_analysis", "expires": 60},
        },
        "process-intelligent-query": {
            "task": "aicommander.queries.process_next",
            "schedule": 5.0,
            "options": {"queue": config.AGENT_REDIS_QUEUE, "expires": 5},
        },
        "process-map-package-import": {
            "task": "aicommander.maps.process_import",
            "schedule": 30.0,
            "options": {"queue": "map_build", "expires": 30},
        },
        "expire-agent-approvals": {
            "task": "aicommander.agent.expire_approvals",
            "schedule": 900.0,
            "options": {"queue": config.AGENT_REDIS_QUEUE},
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
    }
    if not query_creation_enabled(config):
        # Keep the task registered and leave historical approval cleanup intact.
        schedule.pop("process-intelligent-query")
    return schedule


celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule=build_beat_schedule(settings),
)
