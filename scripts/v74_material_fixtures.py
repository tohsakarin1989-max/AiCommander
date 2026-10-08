"""Explicit disposable v7.4 fixtures; never import from an application runtime."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4


def seed_material_case(db, number='V74-SYNTHETIC-001'):
    from app.services.case_result_service import CaseResultService
    from tests.test_case_search_page import add_case
    from tests.test_query_profiles import profile
    # Deliberately unlocated: a result without a frozen map must not invent one.
    case = add_case(db, number, location='合成井场（仅浏览器验收）',
        description='合成测试：发现软管，查获原油120升，未发现车辆。材料仅供隔离验收。',
        occurred_time=datetime(2026, 10, 4, 12))
    profile(db, case)
    saved, _ = CaseResultService.create_current(db, case.id)
    db.commit()
    return case, saved


def seed_v74(db):
    from app.database import bind_principal_scope
    from app.models.analysis_topic import AnalysisTopic, TopicSnapshot
    from app.models.deployment_advisor import SituationBrief
    from app.models.jurisdiction import JurisdictionAsset
    from app.models.user import User
    from app.services import analysis_topic_service as topics
    from app.services.facility_material_service import freeze_facility
    from app.services.intelligent_query_context import result_hash

    user = db.query(User).filter_by(username='v72-analyst').one()
    bind_principal_scope(db, SimpleNamespace(user_id=user.id, role=user.role), method='POST')
    case, saved = seed_material_case(db)
    asset = JurisdictionAsset(name='合成材料井（非真实设施）', asset_type='well', operational_area_id=1,
        latitude=46.5001, longitude=125.1001, verified=False, source='manual', status='active')
    db.add(asset); db.commit()
    frozen, _ = freeze_facility(db, asset.id, idempotency_key='v74-synthetic-facility')
    db.commit()
    topic_ids = []
    for suffix in ('甲', '乙'):
        value = topics.create_topic(db, f'合成同案关注{suffix}', {}, question_kind='case_gaps',
            source_context={'kind': 'case', 'id': case.id})
        topics.refresh_topic(db, value['id'])
        topic = db.get(AnalysisTopic, value['id'])
        first = db.query(TopicSnapshot).filter_by(topic_id=topic.id).one()
        payload = deepcopy(first.payload)
        # Deliberately synthetic notification fixtures, not a claim of measured
        # business change. All subsequent reads, controls and dismissals use API.
        db.add(TopicSnapshot(id=str(uuid4()), topic_id=topic.id, revision=2,
            payload=payload, content_sha256=result_hash(payload),
            changes={'material_changed': True, 'meaningful_items': [{
                'code': 'case_gap', 'message': '合成验收：同案资料变化提示', 'evidence_refs': [f'case:{case.id}']}]},
            created_at=datetime.now(timezone.utc) + timedelta(seconds=1)))
        db.commit(); topic_ids.append(topic.id)
    brief = SituationBrief(id='v74-synthetic-period', operational_area_id=1, period_type='daily',
        period_start=datetime(2026, 10, 3, 16), period_end=datetime(2026, 10, 4, 16),
        input_fingerprint='7' * 64, status='completed', summary='合成固定周期简报，仅供隔离验收。',
        comparison_snapshot={'timezone': 'Asia/Shanghai',
            'current': {'start': '2026-10-03T16:00:00Z', 'end': '2026-10-04T16:00:00Z', 'case_ids': [case.id], 'case_count': 1, 'profile_versions_generated': 1},
            'previous': {'start': '2026-10-02T16:00:00Z', 'end': '2026-10-03T16:00:00Z', 'case_ids': [], 'case_count': 0, 'profile_versions_generated': 0}},
        evidence_refs=[f'case:{case.id}'], information_gaps=['合成数据，不能用于真实业务判断'])
    db.add(brief); db.commit()
    return {'case_id': case.id, 'case_result': saved['id'], 'case_sha256': saved['content_sha256'],
        'facility_id': asset.id, 'facility_material': frozen.id, 'topic_ids': topic_ids, 'situation_id': brief.id}
