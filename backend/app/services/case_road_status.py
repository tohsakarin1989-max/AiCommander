"""Read-only presentation state; never calculate or enqueue on page opening."""
from sqlalchemy import select

from app.models.case_pipeline import OutboxEvent
from app.models.case_road_artifact import CaseRoadArtifact
from app.models.user import User
from app.services.case_result_service import CaseResultService
from app.services.case_road_artifact_service import read_road_artifact
from app.services.case_road_jobs import EVENT_TYPE
from app.services.case_road_triggers import REQUEST_TYPE


def automatic_comparison_status(db, result_id):
    actor = db.info.get('principal_user_id')
    if type(actor) is not int or 'authorized_area_ids' not in db.info:
        raise PermissionError('road_status_not_available')
    if db.scalar(select(User.role).where(User.id == actor, User.is_active.is_(True))) not in ('admin', 'analyst'):
        raise PermissionError('road_status_not_available')
    source = CaseResultService.read(db, result_id)
    base = {'result_id': result_id, 'content_sha256': source['content_sha256'], 'artifact': None}
    # Only the caller's job state is exposed. Other users' payloads, permission
    # scopes and error messages are never returned. Shared artifacts still pass
    # the normal case AND road permission checks below.
    job = db.execute(select(OutboxEvent.status, OutboxEvent.error).where(
        OutboxEvent.event_type == EVENT_TYPE, OutboxEvent.aggregate_id == result_id,
        OutboxEvent.payload['user_id'].as_integer() == actor)
        .order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc()).limit(1)).first()
    if job is None:
        job = db.execute(select(OutboxEvent.status, OutboxEvent.error).where(
            OutboxEvent.event_type == REQUEST_TYPE, OutboxEvent.aggregate_id == result_id,
            OutboxEvent.payload['authority']['user_id'].as_integer() == actor)
            .order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc()).limit(1)).first()
    if job:
        if job.status == 'waiting_dependency':
            return {**base, 'status': 'waiting_network', 'poll_after_seconds': 60}
        if job.status in ('pending', 'retry', 'processing'):
            return {**base, 'status': 'processing', 'poll_after_seconds': 10}
        if job.status == 'completed' and job.error in ('road_job_information_missing', 'road_job_vehicle_information_missing'):
            return {**base, 'status': 'information_missing'}
        if job.status != 'completed':
            return {**base, 'status': 'unavailable'}
    identifier = db.scalar(select(CaseRoadArtifact.id).where(
        CaseRoadArtifact.case_result_id == result_id, CaseRoadArtifact.operation == 'comparison')
        .order_by(CaseRoadArtifact.created_at.desc(), CaseRoadArtifact.id.desc()).limit(1))
    if identifier is None:
        return {**base, 'status': 'not_available'}
    try:
        artifact = read_road_artifact(db, identifier)
    except (PermissionError, ValueError):
        # A failed latest reference must not silently fall back to an old route.
        return {**base, 'status': 'unavailable'}
    return {**base, 'status': 'completed', 'artifact': artifact}
