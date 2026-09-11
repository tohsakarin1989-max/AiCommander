"""Period-end road source changes, not proof of an actual passage change."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json

from app.models.internal_roads import InternalRoadImport, InternalRoadReview
from app.models.map_foundation import MapSource

VERSION = 'road-source-change-4.4-2'
MAX_BATCHES = 2000
MAX_FEATURES = 20000
MAX_REVIEWS = 20000


def _aware(value):
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def condition_state(feature, cutoff):
    """Evaluate the instant before the exclusive period end, not permission."""
    conditions = feature['properties'].get('conditions', {})
    point = cutoff - timedelta(microseconds=1)
    times = {}
    for key in ('valid_from', 'valid_until'):
        raw = conditions.get(key)
        if raw is None:
            continue
        try:
            value = datetime.fromisoformat(raw)
            if value.tzinfo is None:
                return 'invalid_validity'
            times[key] = value
        except (TypeError, ValueError):
            return 'invalid_validity'
    if len(times) == 2 and times['valid_from'] >= times['valid_until']:
        return 'invalid_validity'
    if times.get('valid_from') and point < times['valid_from']:
        return 'not_yet_effective'
    if times.get('valid_until') and point >= times['valid_until']:
        return 'expired'
    return 'within_recorded_interval' if len(times) == 2 else 'validity_incomplete'


def road_source_changes(db, area_id, window):
    """Carry forward absent features; imports are incremental, never deletions."""
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('situation_read_scope_required')
    allowed = db.info['authorized_area_ids']
    if allowed is not None and area_id not in allowed:
        raise PermissionError('situation_area_forbidden')
    result = {'algorithm_version': VERSION, 'state': 'unavailable', 'items': [],
        'import_ids': [], 'review_ids': [], 'information_gaps': [],
        'boundary': '比较期末已登记的道路、入口来源版本；登记时间不是现场变化时间，资料变化不证明实际开通、封闭或可达。未出现的历史要素不自动删除。'}
    query = db.query(InternalRoadImport).join(MapSource).filter(
        InternalRoadImport.operational_area_id == area_id,
        MapSource.operational_area_id == area_id, MapSource.status == 'active',
        InternalRoadImport.created_at < window.current_end)
    before, after = {}, {}
    feature_count = 0
    batches = query.order_by(InternalRoadImport.created_at, InternalRoadImport.id).limit(MAX_BATCHES + 1).yield_per(10)
    for batch_count, batch in enumerate(batches, 1):
        feature_count += len(batch.features)
        if batch_count > MAX_BATCHES or feature_count > MAX_FEATURES:
            result['information_gaps'] = ['道路历史规模超过交互预算，需后台分批比较，未截取部分数据冒充全量。']
            return result
        created = batch.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        for feature in batch.features:
            key = (batch.source_id, feature['id'])
            entry = (batch.id, feature)
            after[key] = entry
            if created < window.current_start:
                before[key] = entry
    if not after:
        result['information_gaps'] = ['本范围尚无可比较的内部道路、入口来源资料。']
        return result
    reviews_before, reviews_after = {}, {}
    review_query = db.query(InternalRoadReview).join(InternalRoadImport).join(MapSource).filter(
        InternalRoadReview.operational_area_id == area_id,
        InternalRoadImport.operational_area_id == area_id,
        MapSource.operational_area_id == area_id, MapSource.status == 'active',
        InternalRoadReview.created_at < window.current_end,
        InternalRoadImport.created_at < window.current_end)
    for count, review in enumerate(review_query.order_by(InternalRoadReview.sequence, InternalRoadReview.id)
                                   .limit(MAX_REVIEWS + 1).yield_per(100), 1):
        if count > MAX_REVIEWS:
            result['information_gaps'] = ['核验历史超过交互预算，未计算部分变化。']
            return result
        key = (review.import_id, review.feature_id)
        value = {'id': review.id, 'decision': review.decision,
                 'connection_evidence_sha256': hashlib.sha256(json.dumps(review.connection_evidence,
                     sort_keys=True, separators=(',', ':')).encode()).hexdigest()}
        reviews_after[key] = value
        if _aware(review.created_at) < window.current_start:
            reviews_before[key] = value
    def status(entry, reviews, cutoff):
        if entry is None:
            return None
        identifier, feature = entry
        review = reviews.get((identifier, feature['id']))
        return {'validity': condition_state(feature, cutoff),
                'review': review, 'review_state': review['decision'] if review else 'unreviewed'}

    statuses = {'previous': {}, 'current': {}}
    for key in sorted(after):
        new_id, new = after[key]
        prior = before.get(key)
        old_status = status(prior, reviews_before, window.current_start)
        new_status = status(after[key], reviews_after, window.current_end)
        statuses['previous'][key] = old_status
        statuses['current'][key] = new_status
        if prior and prior[1] == new and old_status == new_status:
            continue
        fields = []
        if prior:
            old = prior[1]
            if old['geometry'] != new['geometry']:
                fields.append('geometry')
            old_props, props = old['properties'], new['properties']
            fields.extend('properties.' + field for field in sorted(old_props.keys() | props.keys())
                          if old_props.get(field) != props.get(field))
            if old_status['validity'] != new_status['validity']:
                fields.append('condition_validity')
            if old_status['review'] != new_status['review']:
                fields.append('source_review')
        refs = [f'internal_road_import:{new_id}']
        if prior:
            refs.insert(0, f'internal_road_import:{prior[0]}')
        refs.extend(f"internal_road_review:{value['review']['id']}" for value in (old_status, new_status)
                    if value and value['review'])
        props = new['properties']
        result['items'].append({'source_id': key[0], 'feature_id': key[1],
            'name': props['name'], 'kind': props['kind'],
            'change': 'updated_source' if prior else 'newly_recorded', 'changed_fields': fields,
            'previous_conditions': deepcopy(prior[1]['properties'].get('conditions', {})) if prior else None,
            'current_conditions': deepcopy(props.get('conditions', {})),
            'previous_status': old_status, 'current_status': new_status,
            'before_import_id': prior[0] if prior else None, 'after_import_id': new_id,
            'evidence_refs': list(dict.fromkeys(refs)), 'routing_available': None})
    # Include both complete period-end inventories in the digest, not only the
    # displayed changes. No geometry is copied into the brief.
    frozen = {label: [{'source_id': key[0], 'import_id': entry[0], 'feature': entry[1],
                      'status': statuses[label].get(key)}
                     for key, entry in sorted(values.items())]
              for label, values in [('previous', before), ('current', after)]}
    result['input_digest'] = hashlib.sha256(json.dumps(frozen, sort_keys=True,
        ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    result['import_ids'] = sorted({entry[0] for values in (before, after) for entry in values.values()})
    result['review_ids'] = sorted({value['review']['id'] for values in statuses.values()
                                  for value in values.values() if value and value['review']})
    result.update(state='compared', previous_feature_count=len(before), current_feature_count=len(after))
    result['information_gaps'] = ['通行核验、许可及计算路网需单独验证；本项不将来源变化直接认定为通行状态变化。']
    return result


def road_sources_visible(db, snapshot, area_id):
    identifiers = set(snapshot.get('import_ids', []))
    visible = set()
    ordered = sorted(identifiers)
    for start in range(0, len(ordered), 500):
        visible.update(row[0] for row in db.query(InternalRoadImport.id).join(MapSource).filter(
            InternalRoadImport.id.in_(ordered[start:start + 500]),
            InternalRoadImport.operational_area_id == area_id,
            MapSource.operational_area_id == area_id, MapSource.status == 'active').all())
    review_ids = set(snapshot.get('review_ids', []))
    visible_reviews = set()
    ordered_reviews = sorted(review_ids)
    for start in range(0, len(ordered_reviews), 500):
        visible_reviews.update(row[0] for row in db.query(InternalRoadReview.id).filter(
            InternalRoadReview.id.in_(ordered_reviews[start:start + 500]),
            InternalRoadReview.import_id.in_(identifiers),
            InternalRoadReview.operational_area_id == area_id).all())
    return visible == identifiers and visible_reviews == review_ids
