"""Internal-only replay of the production scorer over frozen retrieval inputs.

This captures the current retrieval contract, not arbitrary future query radii
or vehicle routing. Missing frozen queries fail instead of querying live data.
"""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.map_foundation import MapSnapshot
from app.repositories.spatial_repository import SpatialRepository
from app.services.case_insight_service import CaseInsightService, CASE_INSIGHT_ALGORITHM_VERSION
from app.services.scorers.registry import resolve_scorer

SCHEMA = 'frozen-insight-retrieval-4.5-1'
CASE_FIELDS = ('id', 'latitude', 'longitude', 'operational_area_id', 'case_type', 'modus_operandi', 'oil_type')


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def scorer_checksum(version=None):
    return resolve_scorer(version or CASE_INSIGHT_ALGORITHM_VERSION)[1]


def _query_key(kind, arguments):
    values = dict(arguments)
    if 'asset_types' in values:
        values['asset_types'] = sorted(values['asset_types'])
    if 'case' in values:
        values['case'] = {key: getattr(values['case'], key) for key in CASE_FIELDS}
    return checksum({'kind': kind, 'parameters': values})


class CapturingRepository:
    def __init__(self):
        self.queries = {}
        self.case_ids = set()
        self.asset_ids = set()

    def nearby_assets(self, db, **arguments):
        rows = SpatialRepository.nearby_assets(db, **arguments)
        frozen = []
        for asset, distance in rows:
            identifier = CaseInsightService._source_asset_id(asset)
            self.asset_ids.add(identifier)
            attributes = asset.attributes or {}
            frozen.append({'distance_km': distance, 'value': {
                'id': identifier, 'name': asset.name, 'asset_type': asset.asset_type,
                'latitude': asset.latitude, 'longitude': asset.longitude, 'verified': asset.verified,
                'attributes': {key: attributes.get(key) for key in ('oil_type', 'production_output')}}})
        self.queries[_query_key('assets', arguments)] = deepcopy(frozen)
        return rows

    def nearby_cases(self, db, **arguments):
        rows = SpatialRepository.nearby_cases(db, **arguments)
        frozen = []
        for case, distance in rows:
            self.case_ids.add(case.id)
            frozen.append({'distance_km': distance, 'value': {key: getattr(case, key) for key in CASE_FIELDS}})
        self.queries[_query_key('cases', arguments)] = deepcopy(frozen)
        return rows


class FrozenRepository:
    def __init__(self, queries):
        self.queries = queries

    def _read(self, kind, arguments):
        key = _query_key(kind, arguments)
        if key not in self.queries:
            raise ValueError('frozen_query_not_captured')
        return [(SimpleNamespace(**deepcopy(row['value'])), row['distance_km']) for row in self.queries[key]]

    def nearby_assets(self, db, **arguments):
        return self._read('assets', arguments)

    def nearby_cases(self, db, **arguments):
        return self._read('cases', arguments)


def capture_inputs(db, *, case_id, profile_id, snapshot_id):
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('evaluation_scope_required')
    case = db.query(Case).filter(Case.id == case_id).first()
    profile = db.query(CaseAnalysisProfile).filter(CaseAnalysisProfile.id == profile_id,
        CaseAnalysisProfile.case_id == case_id).first()
    snapshot = db.query(MapSnapshot).filter(MapSnapshot.id == snapshot_id).first()
    allowed = db.info['authorized_area_ids']
    if (case is None or profile is None or snapshot is None
            or case.operational_area_id != snapshot.operational_area_id
            or (allowed is not None and case.operational_area_id not in allowed)):
        raise PermissionError('evaluation_inputs_unavailable')
    from app.services.case_pipeline_service import CasePipelineService
    if CasePipelineService.source_hash(db, case) != profile.source_hash:
        raise ValueError('evaluation_profile_source_changed')
    capture = CapturingRepository()
    if case.latitude is not None and case.longitude is not None:
        CaseInsightService._build_candidates(db, case, profile, snapshot, capture)
    payload = {'schema': SCHEMA, 'classification': 'internal_sensitive',
        'algorithm_version': CASE_INSIGHT_ALGORITHM_VERSION, 'scorer_checksum': scorer_checksum(),
        'case': {key: getattr(case, key) for key in CASE_FIELDS},
        'profile': {'id': profile.id, 'source_hash': profile.source_hash, 'profile_version': profile.profile_version},
        'map': {'id': snapshot.id, 'operational_area_id': snapshot.operational_area_id,
                'feature_watermark': snapshot.feature_watermark},
        'queries': capture.queries,
        'source_case_ids': sorted(capture.case_ids | {case.id}), 'source_asset_ids': sorted(capture.asset_ids),
        'boundary': '仅在内网保存的评分输入；包含精确坐标和来源标识，不是可外发的脱敏评测包。冻结检索结果，不包含机动车路由图。'}
    payload = deepcopy(payload)
    return {'payload': payload, 'checksum': checksum(payload)}


def replay_inputs(envelope, *, scorer_policy='captured'):
    """Pure scorer replay; callers must reauthorize source IDs before exposing."""
    payload = envelope['payload']
    if checksum(payload) != envelope['checksum']:
        raise ValueError('frozen_input_checksum_mismatch')
    if scorer_policy not in ('captured', 'current_candidate'):
        raise ValueError('invalid_scorer_policy')
    version = payload.get('algorithm_version') if scorer_policy == 'captured' else CASE_INSIGHT_ALGORITHM_VERSION
    scorer, fingerprint = resolve_scorer(version)
    if (payload.get('schema') != SCHEMA or (scorer_policy == 'captured'
            and payload.get('scorer_checksum') != fingerprint)):
        raise ValueError('frozen_algorithm_unavailable')
    case = SimpleNamespace(**payload['case'])
    if case.latitude is None or case.longitude is None:
        return {'status': 'empty', 'candidates': [], 'information_gaps': ['案件缺少坐标，未生成空间候选。']}
    candidates = scorer._build_candidates(None, case, SimpleNamespace(**payload['profile']),
        SimpleNamespace(**payload['map']), FrozenRepository(payload['queries']))
    return {'status': 'completed' if candidates else 'empty', 'candidates': candidates,
            'information_gaps': [] if candidates else ['冻结输入中没有足够候选依据。']}
