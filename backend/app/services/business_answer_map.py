"""Small frozen map context for a business answer, never a live-coordinate fetch."""
from app.models.case import Case
from app.models.case_source import CaseLocation
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSnapshot, MapSnapshotFeature, MapSource, OperationalArea
from app.services.case_analysis_applicability import exact_point
from app.services.facility_source_access import attributes_sources_visible


LIMIT = 100


def build_map_context(db, question_type, context, data):
    from app.services.business_answer import _hash
    if question_type == 'case_history':
        case_ids = {context['case_id'], *(item['case_id'] for item in data.get('items', []))}
        asset_ids = set()
    elif question_type == 'attention':
        case_ids = set(data.get('source_bindings', {}).get('case_ids', []))
        asset_ids = set(data.get('source_bindings', {}).get('asset_ids', []))
    else:
        case_ids = set(data['current']['case_ids']) | set(data['previous']['case_ids'])
        asset_ids = set()
    snapshots, points, bindings, gaps = {}, [], [], set()
    truncated = False
    states = {}

    def snapshot(area_id):
        if area_id in states:
            return states[area_id]
        area = db.query(OperationalArea).filter_by(id=area_id, status='active').first()
        rows = db.query(MapSnapshot).filter_by(operational_area_id=area_id, status='current').limit(2).all()
        value = rows[0] if area is not None and len(rows) == 1 else None
        states[area_id] = value
        if value is None:
            gaps.add('部分对象所在区域没有唯一有效的已发布地图快照，位置保留未知。')
        else:
            snapshots[value.id] = {'id': value.id, 'version': value.version, 'area_id': area_id}
            bindings.extend([{'kind': 'map_snapshot', 'id': value.id, 'version': _hash(value)},
                             {'kind': 'area', 'id': area.id, 'version': _hash(area)}])
        return value

    def add_point(kind, identifier, label, role, value, base, refs):
        nonlocal truncated
        if len(points) >= LIMIT:
            truncated = True
            return False
        points.append({'kind': kind, 'object_id': identifier, 'label': label, 'role': role,
                       **value, 'map_snapshot_id': base.id, 'evidence_refs': refs})
        return True

    # Assets are few (at most the answer's three displayed objects).
    for identifier in sorted(asset_ids):
        asset = db.query(JurisdictionAsset).filter_by(id=identifier).first()
        if asset is None:
            raise PermissionError('business_answer_map_source_unavailable')
        base = snapshot(asset.operational_area_id)
        if base is None:
            continue
        feature = db.query(MapSnapshotFeature).filter_by(snapshot_id=base.id, asset_id=identifier,
            operational_area_id=asset.operational_area_id).first()
        attrs = (feature.attributes or {}) if feature is not None else {}
        if (feature is None or feature.geometry_type != 'Point'
                or not attributes_sources_visible(db, attrs, asset.operational_area_id)):
            gaps.add('设施没有当前可读的快照点位，未用最新台账坐标代替冻结位置。')
            continue
        geometry = feature.geometry or {'type': 'Point', 'coordinates': [feature.longitude, feature.latitude]}
        value = exact_point({'precision': 'exact', 'geometry': geometry})
        if value is None:
            gaps.add('设施快照坐标不明确，保留未知。')
            continue
        add_point('asset', identifier, feature.name, 'facility', value, base,
                  [f'asset:{identifier}', f'map_feature:{feature.id}', f'map_snapshot:{base.id}'])
        bindings.extend([{'kind': 'map_feature', 'id': feature.id, 'version': _hash(feature)},
                         {'kind': 'asset', 'id': asset.id, 'version': _hash(asset)}])
        source_ids = {attrs.get('source_id')}
        source_ids.update(item.get('source_id') for item in (attrs.get('field_groups') or {}).values())
        for source_id in source_ids - {None}:
            source = db.query(MapSource).filter_by(id=source_id, status='active',
                operational_area_id=asset.operational_area_id).first()
            if source is None:
                raise PermissionError('business_answer_map_source_unavailable')
            bindings.append({'kind': 'map_source', 'id': source.id, 'version': _hash(source)})
    ordered = sorted(case_ids)
    for offset in range(0, len(ordered), 400):
        if truncated:
            break
        batch = ordered[offset:offset + 400]
        cases = {row.id: row for row in db.query(Case).filter(Case.id.in_(batch)).order_by(Case.id)}
        if set(cases) != set(batch):
            raise PermissionError('business_answer_map_case_unavailable')
        found = set()
        rows = db.query(CaseLocation).join(Case, Case.id == CaseLocation.case_id).filter(
            Case.id.in_(batch), CaseLocation.role.in_(['discovery', 'incident']),
            CaseLocation.precision == 'exact').order_by(CaseLocation.case_id, CaseLocation.id)
        for location in rows:
            value = exact_point({'precision': location.precision, 'geometry': location.geometry})
            if value is None:
                continue
            case = cases[location.case_id]
            base = snapshot(case.operational_area_id)
            if base is None:
                continue
            found.add(case.id)
            if not add_point('case', case.id, case.case_number, location.role, value, base,
                             [f'case:{case.id}', f'case_location:{location.id}', f'map_snapshot:{base.id}']):
                break
            bindings.append({'kind': 'case_location', 'id': location.id, 'version': _hash(location)})
        if set(batch) - found:
            gaps.add('部分记录没有明确的发现／案发点；未以文本地点、旧经纬度或附近井位猜测。')
    if truncated:
        gaps.add('地图只展示前 100 个明确点位，不代表全部记录；文字统计与参考范围不因地图上限改变。')
    return {'schema_version': 'business-answer-map-8.4-1',
            'state': 'partial' if points and gaps else 'ready' if points else 'unavailable',
            'snapshots': list(snapshots.values()), 'points': points,
            'coverage': {'point_limit': LIMIT, 'shown': len(points), 'truncated': truncated},
            'information_gaps': sorted(gaps) or ([] if points else ['没有可定位的已知资料。']),
            'boundary': '仅展示本答案冻结的明确点位与地图版本；发现地不等于盗取地，不补造入口、路径或坐标。'}, bindings
