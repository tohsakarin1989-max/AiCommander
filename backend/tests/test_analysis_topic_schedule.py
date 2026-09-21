"""Ordinary saved topics must not depend on the optional Agent Lab worker."""
from app.tasks.analysis_topic_tasks import process_topic
from app.tasks.celery_app import celery_app


def test_topic_schedule_routes_to_default_worker_without_agent_profile():
    entry = celery_app.conf.beat_schedule['process-analysis-topic']
    assert entry['task'] == process_topic.name
    assert entry['schedule'] == 15.0
    assert entry['options']['expires'] == 15
    options = {**process_topic._get_exec_options(), **entry['options']}
    route = celery_app.amqp.router.route(options, process_topic.name, (), {})
    assert route['queue'].name == celery_app.conf.task_default_queue


def test_topic_task_has_bounded_execution_and_no_case_payload():
    assert process_topic.soft_time_limit == 125
    assert process_topic.time_limit == 135
    entry = celery_app.conf.beat_schedule['process-analysis-topic']
    assert not entry.get('args') and not entry.get('kwargs')
