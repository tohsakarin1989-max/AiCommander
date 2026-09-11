"""Replay authorized stored road requests on the exact immutable graph.

The deployment supplies artifact_root. There is no request-controlled path,
graph override, or permission bypass, including for historical evaluations.
"""
from copy import deepcopy
from datetime import datetime

from app.models.road_network import RoadNetworkVersion
from app.services.case_road_artifact_service import read_road_artifact
from app.services.frozen_insight_inputs import checksum
from app.services.road_access_policy import VehicleAssumption
from app.services.road_calculation_service import calculate_distance_matrix, calculate_reference_route
from app.services.road_graph_artifact import verify_graph_artifact
from app.services.road_network_service import resolve_network
from app.services.vehicle_router import RoadCalculationError, RoadLocation

SCHEMA = 'frozen-road-input-4.5-1'


def _request(content):
    schema = content['schema_version']
    operation = 'route' if schema == 'case-road-route-4.2.0-1' else 'matrix' if schema == 'case-road-comparison-4.2.0-1' else None
    if operation is None:
        raise ValueError('unsupported_frozen_road_operation')
    calculation = content['route' if operation == 'route' else 'matrix']
    request = {key: deepcopy(calculation[key]) for key in ('network_id', 'analysis_at', 'vehicle')}
    at = datetime.fromisoformat(request['analysis_at'])
    if at.utcoffset() is None:
        raise ValueError('frozen_road_timezone_required')
    request['vehicle'] = VehicleAssumption.model_validate(request['vehicle']).model_dump()
    if operation == 'route':
        for field in ('origin', 'destination'):
            request[field] = RoadLocation.model_validate(calculation[field]).model_dump()
    else:
        for field in ('sources', 'targets'):
            values = calculation[field]
            if not isinstance(values, list) or not 1 <= len(values) <= 10:
                raise ValueError('frozen_road_matrix_size_invalid')
            request[field] = [RoadLocation.model_validate(value).model_dump() for value in values]
    return operation, request


def _metadata(db, request):
    vehicle = VehicleAssumption.model_validate(request['vehicle'])
    binding = resolve_network(db, request['network_id'], analysis_at=datetime.fromisoformat(request['analysis_at']), vehicle=vehicle)
    row = db.query(RoadNetworkVersion).filter_by(id=binding.network_id).populate_existing().one()
    metadata = {key: getattr(row, key) for key in ('id', 'group_id', 'policy_revision', 'graph_sha256',
        'artifact_key', 'input_sha256', 'conditions_sha256', 'engine_version', 'builder_version', 'public_bundle_id')}
    metadata['source_manifest_checksum'] = checksum(row.source_manifest)
    return binding, metadata


def capture_road_inputs(db, artifact_id, *, artifact_root, verify_files=True):
    artifact = read_road_artifact(db, artifact_id)
    operation, request = _request(artifact['content'])
    binding, metadata = _metadata(db, request)
    if verify_files:
        verify_graph_artifact(artifact_root, binding)
    payload = {'schema': SCHEMA, 'classification': 'internal_sensitive', 'operation': operation,
        'artifact_id': artifact_id, 'artifact_checksum': artifact['content_sha256'],
        'case_result_id': artifact['content']['result_id'], 'case_result_checksum': artifact['content']['content_sha256'],
        'map_snapshot_id': artifact['content']['map_snapshot_id'], 'request': request, 'network': metadata,
        'boundary': '固定已保存的参考路径或矩阵请求；保留原图文件且当前仍有权限时方可重算，不还原实际轨迹。'}
    return {'payload': payload, 'checksum': checksum(payload)}


def validate_road_inputs(db, envelope):
    """Validate current authorization and frozen references without running routing."""
    payload = envelope['payload']
    if checksum(payload) != envelope['checksum'] or payload.get('schema') != SCHEMA:
        raise ValueError('frozen_road_input_integrity_failure')
    artifact = read_road_artifact(db, payload['artifact_id'])
    if artifact['content_sha256'] != payload['artifact_checksum']:
        raise ValueError('frozen_road_source_changed')
    operation, request = _request(artifact['content'])
    if operation != payload['operation'] or request != payload['request']:
        raise ValueError('frozen_road_request_changed')
    _, metadata = _metadata(db, request)
    if metadata != payload['network']:
        raise ValueError('frozen_road_network_changed')
    if (payload['case_result_id'] != artifact['content']['result_id']
            or payload['case_result_checksum'] != artifact['content']['content_sha256']
            or payload['map_snapshot_id'] != artifact['content']['map_snapshot_id']):
        raise ValueError('frozen_road_source_binding_changed')
    return operation, request, metadata


def replay_road_inputs(db, envelope, *, artifact_root, cancel_event=None):
    if cancel_event is not None and cancel_event.is_set():
        raise RoadCalculationError('road_calculation_cancelled')
    operation, request, metadata = validate_road_inputs(db, envelope)
    common = {'network_id': request['network_id'], 'analysis_at': datetime.fromisoformat(request['analysis_at']),
        'vehicle': VehicleAssumption.model_validate(request['vehicle']), 'artifact_root': artifact_root, 'cancel_event': cancel_event}
    if operation == 'route':
        result = calculate_reference_route(db, start=RoadLocation.model_validate(request['origin']),
            end=RoadLocation.model_validate(request['destination']), **common)
    else:
        result = calculate_distance_matrix(db, sources=[RoadLocation.model_validate(value) for value in request['sources']],
            targets=[RoadLocation.model_validate(value) for value in request['targets']], **common)
    # Source permission and integrity can change during the native calculation.
    _, _, current_metadata = validate_road_inputs(db, envelope)
    if current_metadata != metadata:
        raise ValueError('frozen_road_inputs_changed_during_replay')
    if cancel_event is not None and cancel_event.is_set():
        raise RoadCalculationError('road_calculation_cancelled')
    return {'input_checksum': envelope['checksum'], 'result': result, 'result_checksum': checksum(result),
            'execution_task_created': False}
