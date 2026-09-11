"""Select a road vehicle only from frozen evidence; never guess truck dimensions."""
from app.services.road_access_policy import VehicleAssumption
from app.services.case_semantic_structured import extract_structured_sources

TRUCKS = {'truck', '货车', '罐车', '油罐车'}
CARS = {'auto', '小客车', '轿车', 'SUV'}


def frozen_road_vehicle(content):
    """None means required vehicle conditions are missing or ambiguous.

    Only height_m (metres) and gross_weight_t (vehicle total tonnes) are accepted.
    Cargo load, oil quantity, rated payload and vague 'weight' are not total mass.
    """
    semantics = content.get('semantics') or {}
    structured = semantics.get('structured_sources') or {}
    vehicle_fields = {'vehicle_info', 'case_vehicles'}
    if any(item.get('field') in vehicle_fields for item in structured.get('information_gaps', [])):
        return None
    snapshots = [item for item in structured.get('snapshots', []) if item.get('field') in vehicle_fields]
    if len({item['field'] for item in snapshots}) != len(snapshots):
        return None
    records = []
    for snapshot in snapshots:
        checked = extract_structured_sources({snapshot['field']: snapshot.get('value')})
        if checked['information_gaps'] or len(checked['snapshots']) != 1:
            return None
        if checked['snapshots'][0]['sha256'] != snapshot.get('sha256'):
            raise ValueError('road_vehicle_source_hash_mismatch')
        value = snapshot['value']
        if value not in (None, '', {}, []):
            records.extend(value if isinstance(value, list) else [value])
    if len(records) > 1:
        return None  # No evidence that records from different sources describe one vehicle.
    selected = None
    if records:
        record = records[0]
        if isinstance(record, dict):
            # The dedicated road type is independent of legacy bonus categories.
            road_kind = record.get('road_vehicle_kind')
            if road_kind is not None and road_kind not in {'auto', 'truck'}:
                return None
            types = {road_kind} if road_kind is not None else {
                record[key] for key in ('vehicle_type', 'type', '车型') if isinstance(record.get(key), str)}
            if len(types) > 1:
                return None
            kind = next(iter(types), None)
            if kind in TRUCKS:
                if record.get('height_m') is None or record.get('gross_weight_t') is None:
                    return None
                try:
                    selected = VehicleAssumption(kind='truck', height_m=record['height_m'],
                        weight_t=record['gross_weight_t'], source='case_record')
                except ValueError:
                    return None
            elif kind in CARS:
                selected = VehicleAssumption(kind='auto', source='case_record')
            elif kind is not None:
                return None
        elif record not in (None, ''):
            return None
    mentions = [item for item in semantics.get('assertions', [])
                if item.get('category') == 'vehicle' and item.get('kind') != 'negated']
    for item in mentions:
        if item.get('kind') != 'stated':
            return None
        if item.get('value') in TRUCKS:
            if selected is None or selected.kind != 'truck':
                return None
        elif item.get('value') in CARS:
            if selected is not None and selected.kind != 'auto':
                return None
        else:
            return None
    return selected or VehicleAssumption(kind='auto', source='explicit_reference_assumption')
