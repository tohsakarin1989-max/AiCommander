"""Freeze facility scoring alongside the retained old source-candidate scorer."""
from copy import deepcopy

from app.services.case_road_artifact_service import read_road_artifact
from app.services.facility_candidate_pool import require_current_pool_source
from app.services.facility_analysis_versions import SCORING_INPUT_VERSION
from app.services.frozen_insight_inputs import capture_inputs, checksum
from app.services.scorers.facility_roads_v52 import FacilityEvidence, VERSION
from app.services.scorers.registry import resolve_facility_scorer


def capture_facility_inputs(db, artifact_id):
    artifact = read_road_artifact(db, artifact_id)
    content = artifact['content']
    if content.get('schema_version') != 'case-facility-comparison-5.2-1':
        raise ValueError('facility_evaluation_artifact_required')
    pool, result = content['pool'], content['result']
    if ('scoring_evidence' not in result or 'scorer_checksum' not in result
            or result.get('scoring_input_version') != SCORING_INPUT_VERSION):
        raise ValueError('facility_evaluation_inputs_not_recorded')
    require_current_pool_source(db, pool)
    envelope = capture_inputs(db, case_id=_case_id(db, content['result_id']), profile_id=pool['versions']['case_profile_id'],
        snapshot_id=content['map_snapshot_id'], candidate_family='possible_source')
    payload = envelope['payload']
    payload['facility_evaluation'] = {
        'artifact_id': artifact['id'], 'artifact_checksum': artifact['content_sha256'],
        'algorithm_version': result['algorithm_version'], 'scorer_checksum': result['scorer_checksum'],
        'input_schema': result['scoring_input_version'],
        'evidence': deepcopy(result['scoring_evidence']),
        'recall_complete': pool['coverage']['complete'],
        'calculation_complete': result['coverage']['complete'],
        'versions': deepcopy(content['calculation']),
        'retrieval_boundary': '旧来源规则20公里/10设施；新道路池50公里/最多100设施，保留各自召回边界。'}
    envelope['checksum'] = checksum(payload)
    # Validate provenance a second time after archive-time old-map retrieval.
    validate_facility_inputs(db, envelope)
    require_current_pool_source(db, pool)
    return envelope


def _case_id(db, result_id):
    from app.services.case_result_service import CaseResultService
    return CaseResultService.read(db, result_id)['content']['case_id']


def validate_facility_inputs(db, envelope):
    payload = envelope['payload']
    frozen = payload['facility_evaluation']
    artifact = read_road_artifact(db, frozen['artifact_id'])
    content = artifact['content']
    if (artifact['content_sha256'] != frozen['artifact_checksum']
            or content.get('schema_version') != 'case-facility-comparison-5.2-1'
            or payload.get('candidate_family') != 'possible_source'
            or _case_id(db, content['result_id']) != payload['case']['id']
            or content['pool']['versions']['case_profile_id'] != payload['profile']['id']
            or content['map_snapshot_id'] != payload['map']['id']
            or checksum(content['result'].get('scoring_evidence')) != checksum(frozen['evidence'])
            or content['calculation'] != frozen['versions']
            or content['result']['algorithm_version'] != frozen['algorithm_version']
            or content['result']['scorer_checksum'] != frozen['scorer_checksum']
            or content['result'].get('scoring_input_version') != frozen['input_schema']
            or content['pool']['coverage']['complete'] != frozen['recall_complete']
            or content['result']['coverage']['complete'] != frozen['calculation_complete']):
        raise ValueError('facility_evaluation_source_binding_changed')


def replay_facility_inputs(envelope, *, current=False):
    if checksum(envelope['payload']) != envelope['checksum']:
        raise ValueError('frozen_input_checksum_mismatch')
    data = envelope['payload']['facility_evaluation']
    if data['input_schema'] != SCORING_INPUT_VERSION:
        raise ValueError('frozen_facility_input_schema_unavailable')
    version = VERSION if current else data['algorithm_version']
    scorer, code_hash = resolve_facility_scorer(version)
    if not current and code_hash != data['scorer_checksum']:
        raise ValueError('frozen_facility_algorithm_unavailable')
    rows = [FacilityEvidence(**{**item, 'attribute_refs': tuple(item['attribute_refs'])})
            for item in data['evidence']]
    ranked = scorer(rows, recall_complete=data['recall_complete'])
    candidates = [{**item, 'hypothesis_type': 'possible_source', 'region': {}}
                  for item in ranked['candidates']]
    complete = ranked['coverage']['complete']
    return {'status': ('completed' if candidates else 'empty') if complete else 'incomplete',
            'candidates': candidates, 'coverage': ranked['coverage'],
            'information_gaps': [] if complete else ['冻结召回或道路计算未完成，不能将空结果算作正确阴性。']}
