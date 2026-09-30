"""Retired factory behavior now uses the unified reader and version decisions."""
import pytest

from app.models.conclusion import Conclusion
from app.models.conclusion_review import ConclusionReview
from app.models.map_foundation import UserAreaScope
from test_result_materials_v65 import material_db, query_db, search_db, client, saved_case  # noqa: F401
from test_conclusion_result_reuse import saved_legacy


def decision(result, **overrides):
    return {'content_sha256': result['content_sha256'], 'decision': 'retain_reference',
        'note': '该冻结版本仅保留参考', 'idempotency_key': 'api-version-decision', **overrides}


def test_read_list_and_optional_decision_without_generating_duplicate(material_db):
    case, saved = saved_case(material_db)
    with client(material_db) as http:
        path = f"/api/results/case/{saved['id']}"
        result = http.get(path)
        assert result.status_code == 200
        assert result.json()['body']['content'] == saved['content']
        assert result.headers['cache-control'] == 'no-store'
        assert http.get('/api/results?kind=case').json()['items'][0]['id'] == saved['id']
        assert http.post(path + '/judgments', json=decision(saved)).status_code == 201
        repeated = http.post(path + '/judgments', json=decision(saved))
        assert repeated.status_code == 200 and len(repeated.json()['judgments']) == 1
    assert material_db.query(Conclusion).count() == 0 and case.status == 'pending'


def test_absent_result_does_not_generate_or_guess_facts(material_db):
    with client(material_db) as http:
        assert http.get('/api/results/case/missing').status_code == 404
        assert http.post('/api/results/case/missing/judgments',
            json=decision({'content_sha256': '0' * 64})).status_code == 404
    assert material_db.query(Conclusion).count() == 0


def test_changed_original_keeps_historical_version_explicit(material_db):
    case, saved = saved_case(material_db)
    case.description = '后续录入的不同资料'
    material_db.commit()
    with client(material_db) as http:
        response = http.get(f"/api/results/case/{saved['id']}")
    assert response.status_code == 200
    assert response.json()['body']['content'] == saved['content']
    assert '后续录入' not in response.text


@pytest.mark.parametrize('corrupt', ['hash', 'missing', 'malformed'])
def test_corrupt_legacy_source_is_neither_readable_nor_judgeable(material_db, corrupt):
    _, result = saved_case(material_db)
    row = saved_legacy(material_db, result)
    ref = dict(row.evidence['source_result'])
    if corrupt == 'hash':
        ref['content_sha256'] = '0' * 64
    elif corrupt == 'missing':
        ref['result_id'] = 'private-missing-id'
    else:
        ref = None
    row.evidence = {'source_result': ref}
    material_db.commit()
    with client(material_db) as http:
        path = f'/api/results/conclusion/{row.id}'
        assert http.get('/api/results?kind=conclusion').json()['items'] == []
        for response in [http.get(path), http.post(path + '/judgments', json=decision(result))]:
            assert response.status_code == 404
            assert 'private-missing-id' not in response.text
    assert row.status == 'published'
    assert material_db.query(ConclusionReview).count() == 1


def test_read_only_scope_cannot_write_judgment(material_db):
    _, result = saved_case(material_db)
    material_db.query(UserAreaScope).filter_by(user_id=1).update({'access_level': 'read'})
    material_db.commit()
    with client(material_db) as http:
        path = f"/api/results/case/{result['id']}"
        assert http.get(path).status_code == 200
        assert http.post(path + '/judgments', json=decision(result)).status_code == 403


def test_revocation_hides_summary_without_removing_history(material_db):
    case, result = saved_case(material_db)
    row = saved_legacy(material_db, result)
    case.operational_area_id = 2
    material_db.commit()
    with client(material_db) as http:
        response = http.get(f'/api/results/conclusion/{row.id}')
        assert response.status_code == 404 and '人工保留表述' not in response.text
        assert http.get('/api/results?kind=conclusion').json()['items'] == []
    assert material_db.execute(ConclusionReview.__table__.select()).first() is not None
