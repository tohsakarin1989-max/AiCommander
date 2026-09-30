"""Optional human decisions bind exact content; never mutate their source."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database import require_area_write_access
from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset
from app.models.meeting import Meeting
from app.models.result_material import ResultJudgment
from app.services.intelligent_query_tasks import _identity
from app.services.result_catalog import read_result


DECISIONS = {'confirm', 'retain_reference', 'insufficient_evidence', 'exclude_with_evidence'}


def record_judgment(db, kind, identifier, *, content_sha256, decision, note,
                    additional_sources, idempotency_key):
    user = _identity(db)
    if user.role not in {'admin', 'analyst'}:
        raise PermissionError('material_editor_required')
    result = read_result(db, kind, identifier, include_judgments=False)
    if result['content_sha256'] != content_sha256:
        raise ValueError('result_version_conflict')
    if decision not in DECISIONS or not note.strip() or not idempotency_key:
        raise ValueError('invalid_judgment')
    subject = result['subject']
    if subject['kind'] == 'case':
        area = db.query(Case.operational_area_id).filter_by(id=int(subject['id'])).scalar()
        require_area_write_access(db, area)
    elif subject['kind'] == 'facility':
        area = db.query(JurisdictionAsset.operational_area_id).filter_by(id=int(subject['id'])).scalar()
        require_area_write_access(db, area)
    elif subject['kind'] == 'area':
        require_area_write_access(db, int(subject['id']))
    elif subject['kind'] == 'meeting':
        area = db.query(Meeting.operational_area_id).filter_by(meeting_id=subject['id']).scalar()
        require_area_write_access(db, area)
    # Topic/query are owned by the current principal; a decision about their
    # own material is not permission to change the underlying cases.
    for source in additional_sources:
        target = read_result(db, source['kind'], source['id'], include_judgments=False)
        if target['content_sha256'] != source['content_sha256']:
            raise ValueError('additional_source_version_conflict')
    fields = {'result_kind': kind, 'result_id': str(identifier), 'content_sha256': content_sha256,
              'decision': decision, 'note': note.strip(), 'additional_sources': additional_sources}
    existing = db.query(ResultJudgment).filter_by(created_by=user.id, idempotency_key=idempotency_key).first()
    if existing is not None:
        if any(getattr(existing, key) != value for key, value in fields.items()):
            raise ValueError('judgment_idempotency_conflict')
        return existing, False
    dialect = db.get_bind().dialect.name
    insert = pg_insert if dialect == 'postgresql' else sqlite_insert
    identifier = str(uuid4())
    db.execute(insert(ResultJudgment).values(id=identifier, created_by=user.id,
        idempotency_key=idempotency_key, created_at=datetime.now(timezone.utc), **fields)
        .on_conflict_do_nothing(index_elements=['created_by', 'idempotency_key']))
    row = db.query(ResultJudgment).filter_by(created_by=user.id, idempotency_key=idempotency_key).first()
    if row is None or any(getattr(row, key) != value for key, value in fields.items()):
        raise ValueError('judgment_idempotency_conflict')
    return row, row.id == identifier
