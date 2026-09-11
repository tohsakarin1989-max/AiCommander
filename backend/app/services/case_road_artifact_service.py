"""Versioned server-produced road attachments; caller owns the transaction.

Never expose freeze() as an endpoint accepting a client-supplied result body.
Reading a stored artifact rechecks both case evidence and road authorization.
"""
from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4

from sqlalchemy import select, and_, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models.case_road_artifact import CaseRoadArtifact
from app.models.user import User
from app.services.case_result_service import CaseResultService
from app.services.road_access_policy import VehicleAssumption
from app.services.road_network_service import resolve_network


def _encoded(content):
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(encoded.encode()) > 4 * 1024 * 1024:
        raise ValueError('road_artifact_too_large')
    return encoded


def _authorize_content(db, content):
    schema = content.get('schema_version')
    if schema == 'case-road-comparison-4.2.0-1':
        operation, calculation = 'comparison', content.get('matrix')
    elif schema == 'case-road-route-4.2.0-1':
        operation, calculation = 'route', content.get('route')
    else:
        raise ValueError('road_artifact_schema_invalid')
    if not isinstance(calculation, dict):
        raise ValueError('road_artifact_calculation_missing')
    source = CaseResultService.read(db, content['result_id'])
    if (source['content_sha256'] != content['content_sha256']
            or source['content']['versions']['map_snapshot_id'] != content['map_snapshot_id']):
        raise ValueError('road_artifact_source_changed')
    at = datetime.fromisoformat(calculation['analysis_at'])
    vehicle = VehicleAssumption.model_validate_json(json.dumps(calculation['vehicle']))
    binding = resolve_network(db, calculation['network_id'], analysis_at=at, vehicle=vehicle)
    if binding.graph_sha256 != calculation['graph_sha256'] or binding.policy_revision != calculation['policy_revision']:
        raise ValueError('road_artifact_network_changed')
    return source['content']['case_id'], operation, binding.network_id


def freeze_road_artifact(db, content):
    """Only trusted calculation services call this; no commit or source mutation."""
    actor = db.info.get('principal_user_id')
    if type(actor) is not int:
        raise PermissionError('road_artifact_not_authorized')
    role = db.execute(select(User.role).where(User.id == actor, User.is_active.is_(True))).scalar_one_or_none()
    if role not in ('admin', 'analyst'):
        raise PermissionError('road_artifact_not_authorized')
    encoded = _encoded(content)
    frozen = json.loads(encoded)
    case_id, operation, network_id = _authorize_content(db, frozen)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    dialect = db.get_bind().dialect.name
    if dialect not in ('sqlite', 'postgresql'):
        raise ValueError('road_artifact_database_unsupported')
    insert = sqlite_insert if dialect == 'sqlite' else pg_insert
    identifier = db.scalar(insert(CaseRoadArtifact).values(id=str(uuid4()), case_id=case_id,
        case_result_id=frozen['result_id'], network_id=network_id, operation=operation,
        content_sha256=digest, content=frozen, created_by=actor, created_at=datetime.now(timezone.utc))
        .on_conflict_do_nothing(index_elements=['case_result_id', 'created_by', 'content_sha256'])
        .returning(CaseRoadArtifact.id))
    created = identifier is not None
    if identifier is None:
        identifier = db.scalar(select(CaseRoadArtifact.id).where(
            CaseRoadArtifact.case_result_id == frozen['result_id'], CaseRoadArtifact.created_by == actor,
            CaseRoadArtifact.content_sha256 == digest))
    if identifier is None:
        raise PermissionError('road_artifact_not_available')
    return {'id': identifier, 'content_sha256': digest, 'created': created}


def read_road_artifact(db, artifact_id):
    if type(db.info.get('principal_user_id')) is not int or 'authorized_area_ids' not in db.info:
        raise PermissionError('road_artifact_not_authorized')
    row = db.get(CaseRoadArtifact, artifact_id, populate_existing=True)
    if row is None:
        raise PermissionError('road_artifact_not_available')
    encoded = _encoded(row.content)
    if hashlib.sha256(encoded.encode()).hexdigest() != row.content_sha256:
        raise ValueError('road_artifact_integrity_invalid')
    content = json.loads(encoded)
    case_id, operation, network_id = _authorize_content(db, content)
    if (case_id, operation, network_id, content['result_id']) != (
            row.case_id, row.operation, row.network_id, row.case_result_id):
        raise ValueError('road_artifact_binding_invalid')
    created_at = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=timezone.utc)
    return {'id': row.id, 'content_sha256': row.content_sha256, 'created_at': created_at,
            'content': content}


def road_artifact_history(db, result_id, *, limit=10, before_id=None):
    """Keyset pagination; withdrawn road evidence is represented without details."""
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError('road_artifact_page_size_invalid')
    if type(db.info.get('principal_user_id')) is not int or 'authorized_area_ids' not in db.info:
        raise PermissionError('road_artifact_not_authorized')
    CaseResultService.read(db, result_id)
    statement = select(CaseRoadArtifact.id).where(CaseRoadArtifact.case_result_id == result_id)
    if before_id is not None:
        anchor = db.execute(select(CaseRoadArtifact.created_at, CaseRoadArtifact.id).where(
            CaseRoadArtifact.case_result_id == result_id, CaseRoadArtifact.id == before_id)).first()
        if anchor is None:
            raise ValueError('road_artifact_cursor_unavailable')
        statement = statement.where(or_(CaseRoadArtifact.created_at < anchor.created_at,
            and_(CaseRoadArtifact.created_at == anchor.created_at, CaseRoadArtifact.id < anchor.id)))
    ids = list(db.scalars(statement.order_by(CaseRoadArtifact.created_at.desc(),
        CaseRoadArtifact.id.desc()).limit(limit + 1)))
    items = []
    for identifier in ids[:limit]:
        try:
            artifact = read_road_artifact(db, identifier)
        except (PermissionError, ValueError):
            items.append({'id': identifier, 'availability': 'unavailable'})
        else:
            operation = 'comparison' if artifact['content']['schema_version'] == 'case-road-comparison-4.2.0-1' else 'route'
            items.append({'id': identifier, 'availability': 'available', 'operation': operation,
                          'created_at': artifact['created_at'], 'content_sha256': artifact['content_sha256']})
    return {'items': items, 'next_before_id': ids[limit - 1] if len(ids) > limit else None}
