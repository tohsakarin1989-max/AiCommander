"""Fixed synthetic inputs through real business services, in a fresh private DB.

Never accepts a caller session, case ID, text, file, URL or model configuration.
No settings are changed; commit=False bypasses shared vector indexing explicitly.
"""
import asyncio
import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from time import perf_counter

from fastapi.encoders import jsonable_encoder
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.database import Base
from app.agent_runtime.runtime import AgentRunExecutor
from app.agent_runtime.service import AgentRunService
from app.models.case_insight import CaseAnalysisRun
from app.models.case_pipeline import CaseAnalysisProfile, OutboxEvent
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSnapshot, MapSnapshotFeature, OperationalArea, PublicMapBundle
from app.services.case_insight_service import CaseInsightService
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_service import CaseService
from app.services.deployment_advisor_service import DeploymentAdvisorService
from app.services.case_import_table import parse_case_table
from app.services.case_import_values import normalize_case_row


DATASET_VERSION = 'showcase-synthetic-2'
SCENARIOS = ('normal', 'missing_location', 'model_unavailable')
ANCHOR_TIME = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)


class _UnavailableNarrator:
    provider_name = 'showcase_fault_injection'
    model_name = 'injected-timeout'
    input_cost_per_million_usd = 0.0
    output_cost_per_million_usd = 0.0

    def __init__(self):
        self.calls = 0

    async def summarize(self, query, payload):
        self.calls += 1
        raise TimeoutError('showcase_injected_timeout')


def _seed_map(db):
    area = OperationalArea(code='synthetic-only', name='合成演示区（非真实厂区）', is_default=True)
    db.add(area)
    db.flush()
    bundle = PublicMapBundle(bundle_id=DATASET_VERSION, provider='synthetic', source_version='1',
        license_record='project-generated synthetic data', bounds=[124, 46, 126, 47],
        manifest={'synthetic': True, 'renderable': False}, package_hash='0' * 64, status='accepted')
    db.add(bundle)
    db.flush()
    snapshot = MapSnapshot(id='showcase-map-1', version=DATASET_VERSION,
        operational_area_id=area.id, public_bundle_id=bundle.id, status='current',
        manifest={'synthetic': True, 'renderable': False}, feature_watermark=DATASET_VERSION)
    db.add(snapshot)
    db.flush()
    asset = JurisdictionAsset(name='合成设施甲（非实际井位）', asset_type='well',
        operational_area_id=area.id, latitude=46.601, longitude=125.101,
        source='synthetic', status='active', verified=True,
        attributes={'oil_type': '原油', 'production_output': 90})
    db.add(asset)
    db.flush()
    db.add(MapSnapshotFeature(snapshot_id=snapshot.id, operational_area_id=area.id,
        asset_id=asset.id, name=asset.name, asset_type=asset.asset_type, geometry_type='point',
        latitude=asset.latitude, longitude=asset.longitude, source='synthetic', status='active',
        verified=True, attributes=asset.attributes))
    db.commit()
    return area, snapshot, asset


def _execute(db, scenario):
    area, snapshot, asset = _seed_map(db)
    trace = []

    def step(service, operation):
        started = perf_counter()
        value = operation()
        outcome = value[0] if isinstance(value, tuple) else value
        result_status = outcome.get('status') if isinstance(outcome, dict) else getattr(outcome, 'status', None)
        trace.append({'sequence': len(trace) + 1, 'service': service,
                      'duration_ms': round((perf_counter() - started) * 1000, 2),
                      'call_status': 'returned', 'result_status': result_status})
        return value

    payload = {
        'case_number': 'SYNTHETIC-001', 'occurred_time': ANCHOR_TIME,
        'location': '合成演示网格（非真实地点）',
        'latitude': None if scenario == 'missing_location' else 46.6,
        'longitude': None if scenario == 'missing_location' else 125.1,
        'case_type': '涉油盗窃', 'description': '合成案例：夜间发现井口原油损失，存在车辆转运线索，来源与去向待核验。',
        'oil_type': '原油', 'oil_volume': 1.5, 'facility_type': '井口',
        'modus_operandi': '车辆转运', 'operational_area_id': area.id,
    }
    columns = [('案发时间', 'occurred_time'), ('案情描述', 'description'),
               ('案发地点', 'location'), ('纬度', 'latitude'), ('经度', 'longitude'),
               ('案件类型', 'case_type'), ('油品类型', 'oil_type'), ('涉油量', 'oil_volume'),
               ('设施类型', 'facility_type'), ('作案手法', 'modus_operandi')]
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer)
    writer.writerow([label for label, _ in columns])
    writer.writerow([value.isoformat() if isinstance(value, datetime) else value
                     for _, key in columns for value in [payload[key]]])
    content = buffer.getvalue().encode('utf-8-sig')

    def import_table():
        table = parse_case_table('synthetic-cases.csv', content)
        values = normalize_case_row(table.rows[0].values, time_zone='UTC')
        return table, values

    table, values = step('CaseTableParser', import_table)
    payload = {**values, 'case_number': 'SYNTHETIC-001', 'operational_area_id': area.id}
    digest = hashlib.sha256(json.dumps(jsonable_encoder({'case': payload, 'dataset': DATASET_VERSION,
        'map': {'latitude': asset.latitude, 'longitude': asset.longitude, 'attributes': asset.attributes}}),
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def save_case():
        case = CaseService.create_case(db=db, **payload, commit=False)
        db.commit()
        return case

    case = step('CaseService', save_case)
    before = CasePipelineService.source_hash(db, case)
    event = db.query(OutboxEvent).filter_by(aggregate_id=str(case.id),
        event_type='case.analysis.requested').one()
    step('CasePipelineService', lambda: CasePipelineService.process_event(db, event.id))
    profile = db.query(CaseAnalysisProfile).filter_by(case_id=case.id, is_current=True).one()
    insight_event = CaseInsightService.enqueue_analysis(db, profile, snapshot)
    db.commit()
    step('CaseInsightService', lambda: CaseInsightService.process_event(db, insight_event.id))
    run = db.query(CaseAnalysisRun).filter_by(case_id=case.id).one()
    analysis = CaseInsightService.run_to_dict(db, run)
    brief, _ = step('DeploymentAdvisorService', lambda: DeploymentAdvisorService.generate_brief(
        db, operational_area_id=area.id, period_type='daily', as_of=datetime.now(timezone.utc)))
    fault = None
    if scenario == 'model_unavailable':
        narrator = _UnavailableNarrator()
        agent = AgentRunService.create_run(db, task_type='dual_domain_analysis',
            query='合成案例故障演练', case_ids=[case.id], asset_ids=[asset.id], mode='shadow', created_by=None)
        completed = step('AgentRunExecutor', lambda: asyncio.run(
            AgentRunExecutor(narrator=narrator).execute(db, agent.id)))
        fault = {'kind': 'injected_model_timeout', 'calls': narrator.calls, 'status': completed.status,
                 'fallback_mode': completed.result_summary.get('mode')}
    db.refresh(case)
    return jsonable_encoder({
        'dataset_kind': 'synthetic', 'dataset_version': DATASET_VERSION,
        'execution_kind': 'live_deterministic', 'scenario': scenario, 'input_digest': digest,
        'import': {'filename': 'synthetic-cases.csv', 'rows': len(table.rows),
                   'field_mapping': table.field_mapping, 'csv': content.decode('utf-8-sig'),
                   'sha256': hashlib.sha256(content).hexdigest(), 'time_zone': 'UTC'},
        'case': {'id': case.id, **payload},
        'map_features': [{'name': asset.name, 'latitude': asset.latitude, 'longitude': asset.longitude}],
        'profile': {'id': profile.id, 'payload': profile.payload, 'quality_score': profile.quality_score,
                    'schema_version': profile.schema_version, 'dictionary_version': profile.dictionary_version},
        'analysis': analysis, 'brief': DeploymentAdvisorService.brief_to_dict(db, brief),
        'trace': trace, 'fault': fault,
        'original_facts_unchanged': before == CasePipelineService.source_hash(db, case),
        'boundary': '全部案件、设施和坐标均为合成数据；规则实时计算，不是实时模型推理。'
                    '该合成地图快照不可用作离线底图或道路通行证明。候选不是已确认事实。',
    })


def execute_scenario(scenario: str) -> dict:
    if scenario not in SCENARIOS:
        raise ValueError('unsupported_showcase_scenario')
    engine = create_engine('sqlite://')
    try:
        Base.metadata.create_all(engine)
        with Session(engine, autoflush=False) as db:
            return _execute(db, scenario)
    finally:
        engine.dispose()
