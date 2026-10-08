"""Independent bounded index maintenance, with original authorization on reads."""
from copy import deepcopy
import pytest
from sqlalchemy import inspect, insert
from sqlalchemy.orm import Session

from app.models.case_result import CaseResultSnapshot
from app.models.conclusion_review import ConclusionReview
from app.models.report import Report
from app.models.result_catalog import ResultCatalogProjection as Projection, ResultCatalogReference as Reference
from app.services import result_catalog
from app.services.result_catalog_projection import reconcile_catalog
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401
from tests.test_result_materials_v65 import material_db, saved_case, facility  # noqa: F401
from tests.test_result_catalog_v74 import seed_all_kinds, forbid_document_builds, no_sql_writes


def sweep(db, limit=100):
    with Session(db.get_bind()) as service:
        return reconcile_catalog(service, limit=limit)


@pytest.mark.asyncio
async def test_all_kinds_rebuild_metadata_and_explicit_references(material_db, monkeypatch):
    identifiers = await seed_all_kinds(material_db)
    before = result_catalog.catalog(material_db, limit=100)
    forbid_document_builds(monkeypatch)
    result = sweep(material_db)
    assert result['checked'] == result['updated'] == 8 and result['failed'] == 0
    with no_sql_writes(material_db):
        after = result_catalog.catalog(material_db, limit=100)
    assert {item['kind']: item['id'] for item in after['items']} == identifiers
    for old, new in zip(before['items'], after['items'], strict=True):
        assert new.pop('catalog_projection')['state'] == 'ready'
        old.pop('catalog_projection')
        assert new == old
    assert sweep(material_db)['unchanged'] == 8
    rows = material_db.query(Projection).all()
    columns = set(inspect(Projection).columns.keys())
    assert not columns.intersection({'body', 'payload', 'summary', 'content', 'document', 'search_text'})
    assert len(rows) == 8
    # The same source case contributes to several different material stores.
    case = material_db.get(CaseResultSnapshot, identifiers['case']).case_id
    refs = material_db.query(Reference).filter_by(reference_kind='case', reference_id=str(case)).all()
    assert {'case', 'topic', 'facility', 'meeting', 'experience', 'conclusion', 'situation'} <= {
        ref.material_kind for ref in refs}
    assert material_db.query(Reference).filter_by(material_kind='case',
        material_id=identifiers['case'], reference_kind='case_profile').count() >= 1


@pytest.mark.asyncio
async def test_changed_original_and_mutable_child_use_stale_fallback(material_db):
    identifiers = await seed_all_kinds(material_db)
    sweep(material_db)
    report = material_db.get(Report, int(identifiers['meeting']))
    report.content = {'summary': '后补旧报告正文变化'}
    material_db.add(ConclusionReview(conclusion_id=int(identifiers['conclusion']), action='approve', note='新增历史复核'))
    material_db.commit()
    with no_sql_writes(material_db):
        report_view = result_catalog.catalog(material_db, kind='meeting', query='后补旧报告')
        review_view = result_catalog.catalog(material_db, kind='conclusion', query='新增历史复核')
    for view in (report_view, review_view):
        assert view['items'][0]['catalog_projection']['state'] == 'stale_fallback'
    assert sweep(material_db)['updated'] == 2
    assert result_catalog.catalog(material_db, kind='conclusion')['items'][0]['catalog_projection']['state'] == 'ready'


def test_projection_is_neither_a_permission_nor_integrity_grant(material_db):
    from app.models.case import Case
    case, saved = saved_case(material_db)
    sweep(material_db)
    projection = material_db.get(Projection, ('case', saved['id']))
    projection.title = '伪造投影标题'
    material_db.commit()
    item = result_catalog.catalog(material_db, kind='case')['items'][0]
    assert item['title'] != projection.title
    assert item['catalog_projection']['state'] == 'stale_fallback'
    row = material_db.get(CaseResultSnapshot, saved['id'])
    original = deepcopy(row.content)
    row.content = {**original, 'boundary': ['未同步哈希的修改']}
    material_db.commit()
    assert result_catalog.catalog(material_db, kind='case')['items'] == []
    row.content = original
    material_db.commit()
    material_db.query(Case).filter_by(id=case.id).update({'operational_area_id': 2})
    material_db.commit()
    assert result_catalog.catalog(material_db, limit=1)['items'] == []


def test_sweep_is_globally_bounded_restartable_and_failure_isolated(material_db):
    _, bad = saved_case(material_db, '损坏历史材料')
    _, good = saved_case(material_db, '完整历史材料')
    row = material_db.get(CaseResultSnapshot, bad['id'])
    row.content = {}
    material_db.commit()
    first, second = sweep(material_db, 1), sweep(material_db, 1)
    assert first['checked'] == second['checked'] == 1
    assert first['failed'] + second['failed'] == 1
    assert material_db.query(Projection).count() == 2
    assert material_db.get(Projection, ('case', bad['id'])).state == 'failed'
    assert material_db.get(Projection, ('case', good['id'])).state == 'ready'
    assert result_catalog.catalog(material_db, kind='case')['items'][0]['id'] == good['id']


def test_worker_rejects_user_or_pending_save_session_and_does_not_commit_it(material_db):
    from app.models.case import Case
    with pytest.raises(PermissionError, match='clean_service_session'):
        reconcile_catalog(material_db)
    with Session(material_db.get_bind()) as service:
        row = Case(case_number='未提交保存', description='保存事务不能带索引任务', operational_area_id=1)
        service.add(row)
        with pytest.raises(PermissionError, match='clean_service_session'):
            reconcile_catalog(service)
        assert row in service.new
        service.rollback()
    assert material_db.query(Case).filter_by(case_number='未提交保存').count() == 0
    assert material_db.query(Projection).count() == 0


def test_worker_does_not_commit_already_flushed_core_business_writes(material_db):
    from app.models.case import Case
    with Session(material_db.get_bind()) as service:
        service.execute(insert(Case).values(case_number='CORE-NOT-COMMITTED', description='未提交原文', operational_area_id=1))
        assert not service.new and not service.dirty
        with pytest.raises(PermissionError, match='clean_service_session'):
            reconcile_catalog(service)
        service.rollback()
    assert material_db.query(Case).filter_by(case_number='CORE-NOT-COMMITTED').count() == 0


def test_disposable_index_can_be_rebuilt_without_changing_saved_material(material_db):
    _, saved = saved_case(material_db)
    sweep(material_db)
    with Session(material_db.get_bind()) as service:
        service.query(Reference).delete()
        service.query(Projection).delete()
        service.commit()
    assert result_catalog.catalog(material_db)['items'][0]['catalog_projection']['state'] == 'legacy_fallback'
    assert sweep(material_db)['updated'] == 1
    assert material_db.query(Reference).count() >= 2
    original = material_db.get(CaseResultSnapshot, saved['id'])
    assert original.content == saved['content'] and original.content_sha256 == saved['content_sha256']


def test_sweep_repairs_damaged_metadata_and_missing_reverse_references(material_db):
    _, saved = saved_case(material_db)
    sweep(material_db)
    row = material_db.get(Projection, ('case', saved['id']))
    row.title = '投影损坏，不是事实变化'
    material_db.query(Reference).delete()
    material_db.commit()
    assert sweep(material_db)['updated'] == 1
    material_db.expire_all()
    assert material_db.get(Projection, ('case', saved['id'])).title != '投影损坏，不是事实变化'
    assert material_db.query(Reference).count() >= 2
    assert result_catalog.catalog(material_db)['items'][0]['catalog_projection']['state'] == 'ready'


def test_metadata_topic_listing_does_not_build_views(material_db, monkeypatch):
    from app.services import analysis_topic_service as topics
    saved_case(material_db)
    topic = topics.create_topic(material_db, '投影不等于正文', {})
    assert topics.refresh_topic(material_db, topic['id'])['status'] == 'updated'
    def forbidden(*args, **kwargs):
        pytest.fail('metadata listing must not build topic presentation views')
    monkeypatch.setattr(topics, 'read_topic_views', forbidden)
    assert len(result_catalog.catalog(material_db, kind='topic')['items']) == 1


def test_subject_filter_uses_original_metadata_before_body_assembly(material_db, monkeypatch):
    case, wanted = saved_case(material_db, '目标案件')
    saved_case(material_db, '其他案件')
    original = result_catalog._read_content
    read_ids = []
    def read(db, kind, identifier, **kwargs):
        read_ids.append(identifier)
        return original(db, kind, identifier, **kwargs)
    monkeypatch.setattr(result_catalog, '_read_content', read)
    items = result_catalog.catalog(material_db, subject_kind='case', subject_id=str(case.id))['items']
    assert [item['id'] for item in items] == [wanted['id']]
    assert read_ids == [wanted['id']]
    # Keep the old exact-string subject semantics; do not coerce '01' to 1.
    assert result_catalog.catalog(material_db, subject_kind='case', subject_id=f'0{case.id}')['items'] == []


def test_worker_schedule_is_independent_of_model_flags():
    from types import SimpleNamespace
    from app.tasks.celery_app import build_beat_schedule
    schedule = build_beat_schedule(SimpleNamespace(ENABLE_INTELLIGENT_QUERY=False, AGENT_REDIS_QUEUE='agent'))
    assert schedule['reconcile-material-catalog']['task'] == 'aicommander.materials.reconcile_catalog'
    assert schedule['reconcile-material-catalog']['schedule'] == 60.0
