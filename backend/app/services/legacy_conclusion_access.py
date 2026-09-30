"""Read-only authorization for preserved old decisions; no conclusion factory."""
from app.models.case import Case
from app.models.meeting import Meeting
from app.services.case_result_access import CaseResultAccessError
from app.services.case_result_service import CaseResultService
from app.services.meeting_frozen_service import require_meeting_sources


def require_conclusion_result_access(db, conclusion):
    if 'authorized_area_ids' not in db.info or db.query(Case.id).filter_by(id=conclusion.case_id).first() is None:
        raise CaseResultAccessError()
    evidence = conclusion.evidence if isinstance(conclusion.evidence, dict) else {}
    source = evidence.get('source_result')
    try:
        if 'source_result' in evidence:
            if not isinstance(source, dict):
                raise CaseResultAccessError()
            result = CaseResultService.read(db, source['result_id'])
            if (result['content']['case_id'] != conclusion.case_id
                    or result['content_sha256'] != source['content_sha256']
                    or result['content']['schema_version'] != source['schema_version']
                    or result['content']['versions'] != source['versions']):
                raise CaseResultAccessError()
        if conclusion.meeting_id:
            meeting = db.query(Meeting).filter_by(meeting_id=conclusion.meeting_id).first()
            if meeting is None:
                raise CaseResultAccessError()
            require_meeting_sources(db, meeting)
    except (KeyError, TypeError, ValueError, PermissionError):
        raise CaseResultAccessError() from None
