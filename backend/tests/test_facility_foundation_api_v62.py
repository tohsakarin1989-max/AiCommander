"""Synthetic identity/context and source-bound recording integration."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from app.models.case_facility_association import CaseFacilityAssociation
from app.models.case_source import CaseRevision, SourceReference, EvidenceObject
from app.models.case import CaseEvidence
from app.models.map_foundation import UserAreaScope, MapSource
from app.models.user import User
from app.services.case_service import CaseService
from app.services.case_source_service import CaseSourceService
from app.services.facility_execution_context import freeze_facility_context
from app.services.facility_summary_service import read_dossier
from tests.test_facility_summary import asset, client
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401


@pytest.fixture
def recorded(query_db):
    db = query_db
    db.query(UserAreaScope).filter_by(user_id=1).one().access_level = 'write'
    db.commit()
    # Refresh persisted grants rather than trusting stale fixture db.info.
    freeze_facility_context(db)
    facility = asset(db)
    case = CaseService.create_case(db, case_number='V62-SYNTHETIC', operational_area_id=1,
        occurred_time=datetime(2026, 9, 1), description='合成原文明确提及设施A，来源仍待核验')
    revision = CaseSourceService.latest_revision(db, case.id)
    reference = SourceReference(case_id=case.id, source_revision_id=revision.id,
        kind='text', locator={'field': 'description', 'start': 0, 'end': 14})
    db.add(reference)
    db.commit()
    return db, facility, case, {'case_id': case.id, 'source_revision_id': revision.id,
        'source_reference_id': reference.id, 'relation_type': 'mentioned',
        'note': '依据合成原文记录提及关系，不确认实际来源', 'request_key': 'synthetic-request-001'}


def test_material_recording_idempotence_and_revoke_preserve_original(recorded):
    db, facility, case, payload = recorded
    original = case.description
    with client(db) as http:
        created = http.post(f'/api/facility-analysis/assets/{facility.id}/case-links', json=payload)
        assert created.status_code == 201, created.text
        identifier = created.json()['id']
        assert http.post(f'/api/facility-analysis/assets/{facility.id}/case-links', json=payload).status_code == 200
        assert db.query(CaseFacilityAssociation).count() == 1
        assert db.query(CaseRevision).count() == 1
        view = http.get(f'/api/facility-analysis/assets/{facility.id}').json()
        link = view['sections']['record_links']['items'][0]
        assert link['association_id'] == identifier and link['relation_kind'] == 'recorded_material_link'
        assert link['source_state'] == 'current' and link['status'] == 'recorded'
        revoked = http.post(f'/api/facility-analysis/case-links/{identifier}/revoke', json={'note': '重新核对后撤销'})
        assert revoked.status_code == 200 and revoked.json()['status'] == 'revoked'
        assert db.query(CaseFacilityAssociation).count() == 1
        assert case.description == original


def test_material_recording_rejects_read_only_and_stale_basis(recorded):
    db, facility, case, payload = recorded
    with client(db) as http:
        changed = CaseService.update_case(db, case.id, description='原文已修订，不自动继承旧判断')
        assert changed.description != 'unused'
        assert http.post(f'/api/facility-analysis/assets/{facility.id}/case-links', json=payload).status_code == 409
        payload['source_revision_id'] = CaseSourceService.latest_revision(db, case.id).id
        db.query(UserAreaScope).filter_by(user_id=1).one().access_level = 'read'
        db.commit()
        assert http.post(f'/api/facility-analysis/assets/{facility.id}/case-links', json=payload).status_code == 403
        assert db.query(CaseFacilityAssociation).count() == 0


def test_material_recording_never_reads_other_scope_or_fabricates_reference(recorded):
    db, facility, _, payload = recorded
    hidden = asset(db, area=2, name='不可见设施')
    with client(db) as http:
        assert http.post(f'/api/facility-analysis/assets/{hidden.id}/case-links', json=payload).status_code == 403
        payload['source_reference_id'] = 98765
        assert http.post(f'/api/facility-analysis/assets/{facility.id}/case-links', json=payload).status_code == 422
        assert http.get(f'/api/facility-analysis/assets/{hidden.id}/case-links').status_code == 404


def test_prior_record_is_marked_stale_after_source_update(recorded):
    db, facility, case, payload = recorded
    with client(db) as http:
        assert http.post(f'/api/facility-analysis/assets/{facility.id}/case-links', json=payload).status_code == 201
        CaseService.update_case(db, case.id, description='后续补录有不同条件')
        view = http.get(f'/api/facility-analysis/assets/{facility.id}').json()
        row = view['sections']['record_links']['items'][0]
        assert row['source_state'] == 'stale' and '需重新核对' in str(row['gaps'])


def test_old_text_reference_cannot_be_combined_with_new_revision(recorded):
    db, facility, case, payload = recorded
    CaseService.update_case(db, case.id, description='已删除原设施提及')
    payload['source_revision_id'] = CaseSourceService.latest_revision(db, case.id).id
    with client(db) as http:
        response = http.post(f'/api/facility-analysis/assets/{facility.id}/case-links', json=payload)
        assert response.status_code == 422
        assert db.query(CaseFacilityAssociation).count() == 0


def test_uploaded_material_reference_uses_current_revision_membership(recorded):
    db, facility, case, payload = recorded
    material = EvidenceObject(storage_key='synthetic-62', sha256='a' * 64,
        media_type='application/pdf', sensitivity='internal', availability='available', content=b'synthetic')
    db.add(material)
    db.flush()
    reference = SourceReference(case_id=case.id, evidence_object_id=material.id,
        kind='evidence', locator={'title': '合成材料'})
    db.add(reference)
    db.flush()
    db.add(CaseEvidence(case_id=case.id, source_reference_id=reference.id,
        evidence_object_id=material.id, title='合成材料'))
    revision, _ = CaseSourceService.capture_change(db, case)
    db.commit()
    assert reference.source_revision_id is None
    payload.update(source_reference_id=reference.id, source_revision_id=revision.id)
    with client(db) as http:
        response = http.post(f'/api/facility-analysis/assets/{facility.id}/case-links', json=payload)
        assert response.status_code == 201, response.text
        assert response.json()['source_state'] == 'current'


def test_context_rechecks_account_and_does_not_treat_url_as_permission(query_db):
    db = query_db
    first = freeze_facility_context(db, area_id=1)
    assert first.road_permission == 'resolve_separately_from_current_grants'
    with pytest.raises(PermissionError):
        freeze_facility_context(db, area_id=2)
    with pytest.raises(ValueError):
        freeze_facility_context(db, known_at=datetime.now(timezone.utc) + timedelta(days=1))
    db.query(UserAreaScope).filter_by(user_id=1).delete()
    db.commit()
    after = freeze_facility_context(db)
    assert after.policy_version != first.policy_version and after.authorized_area_ids == ()
    db.get(User, 1).is_active = False
    db.commit()
    with pytest.raises(PermissionError):
        freeze_facility_context(db)


def test_dossier_and_inventory_do_not_write_and_restrict_admin_list(query_db):
    db = query_db
    facility = asset(db)
    writes = []
    def capture(conn, cursor, statement, params, context, many):
        if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(statement)
    event.listen(db.get_bind(), 'before_cursor_execute', capture)
    try:
        with client(db) as http:
            response = http.get(f'/api/facility-analysis/assets/{facility.id}?valid_at=2020-01-01T00:00:00Z&known_at=2020-01-02T00:00:00Z')
            assert response.status_code == 200, response.text
            result = response.json()
            assert result['temporal_context']['state'] == 'unknown'
            assert result['temporal_context']['snapshot'] is None
            assert result['computability']['route_state'] == 'not_checked'
            assert http.get('/api/facility-analysis/readiness').status_code == 403
            assert http.get('/api/facility-analysis/identities?asset_id=1').status_code == 403
            assert writes == []
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', capture)


def test_hidden_historical_source_is_restricted_not_server_error(query_db):
    db = query_db
    facility = asset(db)
    source = MapSource(source_key='v62-hidden-source', name='不可泄露来源名',
        source_type='ledger', operational_area_id=2, status='active')
    db.add(source)
    db.flush()
    facility.attributes = {'source_id': source.id, 'oil_type': '不可泄露油品'}
    db.commit()
    with client(db) as http:
        value = http.get(f'/api/facility-analysis/assets/{facility.id}')
        assert value.status_code == 200, value.text
        assert value.json()['sections']['production']['state'] == 'restricted'
        assert '不可泄露' not in value.text


def test_admin_inventory_returns_source_scope_and_no_route_claim(query_db):
    db = query_db
    asset(db)
    db.get(User, 1).role = 'admin'
    db.commit()
    with client(db) as http:
        value = http.get('/api/facility-analysis/readiness?operational_area_id=1&page_size=1')
        assert value.status_code == 200, value.text
        assert value.json()['context']['operational_area_id'] == 1
        assert value.json()['items'][0]['route_state'] == 'not_checked'
        assert http.get('/api/facility-analysis/readiness?page_size=101').status_code == 422
