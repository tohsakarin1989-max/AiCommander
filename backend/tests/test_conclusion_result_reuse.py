"""旧工厂退役后，保留历史判断并验证统一成果只读和可选版本判断。"""
from copy import deepcopy

import pytest
from sqlalchemy import event, select

from app.database import AreaWriteAccessError
from app.models.case import Case
from app.models.conclusion import Conclusion
from app.models.conclusion_review import ConclusionReview
from app.models.case_result import CaseResultSnapshot
from app.models.map_foundation import MapSnapshot
from app.services.case_intelligence_service import CaseIntelligenceService
from app.services.case_pipeline_service import (
    CASE_DICTIONARY_VERSION,
    CASE_PROFILE_SCHEMA_VERSION,
    CasePipelineService,
)
from app.services.case_result_access import CaseResultAccessError
from app.services.case_result_service import CaseResultService
from test_case_result_access import result_data  # noqa: F401


@pytest.fixture
def current_profile(db_session, result_data):
    profile, _, candidate = result_data
    db_session.info.update(authorized_area_ids=(1, 2), area_access_levels={1: "write"})
    case = db_session.scalar(select(Case).where(Case.id == 1))
    case.location = "合成地点"
    db_session.flush()
    source_hash = CasePipelineService.source_hash(db_session, case)
    profile.source_hash = source_hash
    profile.schema_version = CASE_PROFILE_SCHEMA_VERSION
    profile.dictionary_version = CASE_DICTIONARY_VERSION
    profile.payload = {
        **profile.payload, "source_hash": source_hash,
        "critical_gaps": [{"field": "oil_type", "label": "缺少油品类型"}],
    }
    candidate.counter_evidence = ["现有资料未证明与该设施有实际联系"]
    db_session.execute(MapSnapshot.__table__.update().values(status="current"))
    db_session.commit()
    return profile


@pytest.fixture
def frozen_result(db_session, current_profile):
    result, _ = CaseResultService.create_current(db_session, 1)
    db_session.commit()
    assert CaseResultService.latest(db_session, 1)["freshness"] == "current"
    return result


@pytest.fixture
def forbid_analysis(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("结论草稿不得重跑模型、原文分析或相似检索")

    for name in ("build_report", "build_experience_card", "find_similar_cases", "build_prevention_suggestions"):
        monkeypatch.setattr(CaseIntelligenceService, name, forbidden)


from app.services.legacy_conclusion_access import require_conclusion_result_access
from app.services.result_catalog import read_result
from app.services.result_judgment_service import record_judgment
from test_result_materials_v65 import material_db, query_db, search_db, saved_case  # noqa: F401


def saved_legacy(db, result, *, status='published'):
    row = Conclusion(case_id=result['content']['case_id'], status=status,
        summary='人工保留表述', evidence={'confidence_available': False, 'source_result': {'result_id': result['id'],
            'content_sha256': result['content_sha256'], 'schema_version': result['content']['schema_version'],
            'versions': deepcopy(result['content']['versions'])}})
    db.add(row)
    db.flush()
    db.add(ConclusionReview(conclusion_id=row.id, action='approve', note='保留的历史人工记录'))
    db.commit()
    return row


def test_frozen_reader_reuses_body_no_factory_or_new_conclusion(material_db, forbid_analysis):
    case, result = saved_case(material_db)
    original = case.description
    first = read_result(material_db, 'case', result['id'])
    assert read_result(material_db, 'case', result['id']) == first
    assert first['body']['content'] == result['content']
    assert first['judgments'] == []
    assert material_db.query(Conclusion).count() == 0
    assert case.description == original


@pytest.mark.parametrize('status,action', [('published', 'approve'), ('rejected', 'reject'), ('flagged', 'flag')])
def test_history_status_reviews_and_summary_survive_repeat_read(material_db, status, action):
    _, result = saved_case(material_db)
    row = saved_legacy(material_db, result, status=status)
    review = material_db.query(ConclusionReview).one()
    review.action = action
    material_db.commit()
    original = deepcopy(row.evidence)
    first = read_result(material_db, 'conclusion', str(row.id))
    assert read_result(material_db, 'conclusion', str(row.id)) == first
    assert first['body']['status'] == status
    assert first['body']['historical_reviews'][0]['action'] == action
    assert first['body']['historical_reviews'][0]['reviewer_state'] == 'legacy_not_recorded'
    assert row.summary == '人工保留表述' and row.evidence == original
    assert material_db.query(ConclusionReview).count() == 1


def test_optional_judgment_does_not_create_factory_draft_or_reset_history(material_db):
    case, result = saved_case(material_db)
    legacy = saved_legacy(material_db, result)
    request = dict(content_sha256=result['content_sha256'], decision='insufficient_evidence',
        note='对该版保留信息不足判断', additional_sources=[], idempotency_key='old-to-new-decision')
    first, _ = record_judgment(material_db, 'case', result['id'], **request)
    material_db.commit()
    retry, created = record_judgment(material_db, 'case', result['id'], **request)
    assert retry.id == first.id and not created
    assert legacy.status == 'published' and case.status == 'pending'
    assert material_db.query(Conclusion).count() == 1
    assert material_db.query(ConclusionReview).count() == 1


@pytest.mark.parametrize('invalid', [None, {}, {'result_id': 'missing'}])
def test_malformed_legacy_source_never_falls_back_to_unversioned_record(material_db, invalid):
    _, result = saved_case(material_db)
    row = saved_legacy(material_db, result)
    row.evidence = {'source_result': invalid}
    material_db.commit()
    with pytest.raises(CaseResultAccessError):
        require_conclusion_result_access(material_db, row)
    with pytest.raises(PermissionError):
        read_result(material_db, 'conclusion', str(row.id))


def test_source_revocation_blocks_historical_judgment_but_does_not_delete_it(material_db):
    case, result = saved_case(material_db)
    row = saved_legacy(material_db, result)
    case.operational_area_id = 2
    material_db.commit()
    with pytest.raises(CaseResultAccessError):
        require_conclusion_result_access(material_db, row)
    assert material_db.execute(ConclusionReview.__table__.select()).first() is not None
