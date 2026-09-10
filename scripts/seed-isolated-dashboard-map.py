#!/usr/bin/env python3
"""Fixed synthetic case + facility in the exact disposable map integration DB.

Run only inside aic-map-auto-api. Existing public MBTiles are reused unchanged.
"""
import json
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.database import SessionLocal
from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile, OutboxEvent
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSnapshot
from app.models.user import User
from app.services.case_service import CaseService
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_insight_service import CaseInsightService
from app.services.offline_map_service import OfflineMapService


def main():
    if settings.DATABASE_URL != 'sqlite:////var/lib/aicommander/maps/queue-smoke.sqlite':
        raise RuntimeError('refuse_non_disposable_database')
    with SessionLocal() as db:
        if db.query(User).filter_by(username='queue-map-test', role='admin').first() is None:
            raise RuntimeError('disposable_owner_missing')
        if db.query(Case).count():
            raise RuntimeError('refuse_populated_database')
        previous = db.query(MapSnapshot).filter_by(
            id='ceedad27-b860-4438-8590-dd0419af6b30', status='current', operational_area_id=1).one()
        asset = JurisdictionAsset(name='联合验收合成井（非真实井场）', asset_type='well',
            operational_area_id=1, latitude=46.601, longitude=125.101,
            source='synthetic', status='active', verified=True,
            attributes={'oil_type': '原油', 'production_output': 90})
        db.add(asset)
        db.commit()
        snapshot, reused = OfflineMapService.build_snapshot(db, operational_area_id=1,
            public_bundle_id=previous.public_bundle_id, built_by=None)
        if reused:
            raise RuntimeError('unexpected_preexisting_snapshot')
        OfflineMapService.publish_snapshot(db, snapshot.id)
        case = CaseService.create_case(db=db, commit=False, case_number='SYNTHETIC-DASHBOARD-001',
            occurred_time=datetime.now(timezone.utc) - timedelta(hours=1), operational_area_id=1,
            location='合成演示网格（非真实案发地点）', latitude=46.6, longitude=125.1,
            case_type='涉油盗窃', description='合成案例：发现井口原油损失，存在车辆转运线索，来源与去向待核验。',
            oil_type='原油', facility_type='井口', modus_operandi='车辆转运')
        db.commit()
        before = CasePipelineService.source_hash(db, case)
        event = db.query(OutboxEvent).filter_by(aggregate_id=str(case.id),
            event_type='case.analysis.requested').one()
        CasePipelineService.process_event(db, event.id)
        profile = db.query(CaseAnalysisProfile).filter_by(case_id=case.id, is_current=True).one()
        insight_event = CaseInsightService.enqueue_analysis(db, profile, snapshot)
        db.commit()
        CaseInsightService.process_event(db, insight_event.id)
        db.refresh(case)
        assert before == CasePipelineService.source_hash(db, case)
        print(json.dumps({'synthetic': True, 'case_id': case.id, 'profile_id': profile.id,
            'snapshot_id': snapshot.id, 'previous_snapshot_id': previous.id,
            'public_bundle_id': snapshot.public_bundle_id, 'public_tiles_rebuilt': False,
            'original_case_unchanged': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
