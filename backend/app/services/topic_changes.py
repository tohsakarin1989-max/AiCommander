"""Business changes, not queue transitions or routine refresh timestamps."""
from copy import deepcopy
from app.services.intelligent_query_context import result_hash


def road_business_state(content):
    comparison = (content.get('result') or {}).get('condition_comparison')
    if comparison:
        return {'candidates': [{'asset_id': row['asset_id'], 'eligibility': row['eligibility'],
            'rank': row['rank'], 'conditions': [{'key': item['key'], 'state': item['state'],
                'reason': item['reason']} for item in row['conditions']]}
            for row in comparison['rows']]}
    calculation = content.get('matrix') or content.get('calculation') or content.get('route') or {}
    return {key: calculation.get(key) for key in ('cells', 'state', 'distance_m', 'duration_seconds')}


def comparable_payload(payload):
    value = deepcopy(payload)
    definition = value.get('definition')
    if definition:
        definition.pop('as_of', None)
    # Catalog background checked times and page read times are not new evidence.
    if value.get('facility_context'):
        value['facility_context'] = business_context(value['facility_context'], 'facility')
    if value.get('case_context'):
        value['case_context'] = business_context(value['case_context'], 'case')
    return value


def business_context(content, kind):
    value = deepcopy(content)
    value.pop('generated_at', None)
    value.pop('pipeline', None)
    if kind == 'facility':
        # This catalog cache merely catches up to source data already displayed.
        value.pop('summary', None)
        value.get('versions', {}).pop('view_version', None)
    return value


def semantic_changes(previous, current):
    if previous is None:
        return {'material_changed': False, 'meaningful_items': []}
    items = []
    old, new = previous['aggregate'], current['aggregate']
    old_ids = {row['case_id'] for row in old['members']}
    new_ids = {row['case_id'] for row in new['members']}
    if old_ids != new_ids:
        items.append({'code': 'membership_changed', 'message': f'符合关注条件的案件新增 {len(new_ids-old_ids)} 起、移出 {len(old_ids-new_ids)} 起。',
            'evidence_refs': [f'case:{value}' for value in sorted(old_ids ^ new_ids)[:3]]})
    old_unknown = {row['case_id'] for row in old.get('unknown', [])}
    new_unknown = {row['case_id'] for row in new.get('unknown', [])}
    resolved = [row for row in new['source_manifest'] if row['case_id'] in old_unknown - new_unknown
                and row['state'] == 'ready' and row['profile_id']]
    if resolved:
        items.append({'code': 'gaps_resolved', 'message': '部分原来资料不足的案件已有可核对条件。',
            'evidence_refs': [f"case_profile:{row['profile_id']}" for row in resolved[:3]]})
    if result_hash(old['condition_statistics']) != result_hash(new['condition_statistics']) or result_hash(old['patterns']) != result_hash(new['patterns']):
        items.append({'code': 'conditions_changed', 'message': '同一关注问题的支持、相反或不确定条件分布发生变化。',
            'evidence_refs': [f"case:{row['case_id']}" for row in new['source_manifest'][:3]]})
    old_roads = previous.get('references', {}).get('roads', [])
    new_roads = current.get('references', {}).get('roads', [])
    old_road_state = {row['case_id']: row.get('business_state', {'legacy_reference': row['id']}) for row in old_roads}
    new_road_state = {row['case_id']: row.get('business_state', {'legacy_reference': row['id']}) for row in new_roads}
    if old_road_state != new_road_state:
        unavailable = set(old_road_state) - set(new_road_state)
        items.append({'code': 'road_basis_changed', 'message': '道路或候选依据已有新版本，请对照原结果核对；不代表实际通行已证实。',
            'evidence_refs': ([f"case_road_artifact:{row['id']}" for row in new_roads[:3]]
                              or [f'case:{case_id}' for case_id in sorted(unavailable)[:3]])})
        if unavailable:
            items[-1].update(code='road_basis_unavailable', message='原有道路依据现已过期或受限，不能继续作为当前通行依据；等待有效版本，不以直线距离替代。')
        previously = {(case_id, candidate['asset_id']): candidate for case_id, state in old_road_state.items()
                      for candidate in state.get('candidates', [])}
        candidates = [(case_id, candidate) for case_id, state in new_road_state.items() for candidate in state.get('candidates', [])]
        excluded = [candidate for case_id, candidate in candidates if candidate['eligibility'] == 'excluded'
            and previously.get((case_id, candidate['asset_id']), {}).get('eligibility') not in (None, 'excluded')]
        if excluded:
            items.insert(0, {'code': 'candidate_excluded', 'message': f'{len(excluded)} 项原候选因新依据被硬限制排除；不自动改变案件事实。',
                'evidence_refs': [f"case_road_artifact:{row['id']}" for row in new_roads[:3]]})
    for field, code, label in [('case_context', 'case_information_changed', '所关注案件的缺口或已有依据变化'),
                              ('facility_context', 'facility_conditions_changed', '所关注设施的分类资料或缺口变化')]:
        kind = 'case' if field == 'case_context' else 'facility'
        if current.get(field) and result_hash(business_context(current[field], kind)) != result_hash(business_context(previous.get(field) or {}, kind)):
            items.append({'code': code, 'message': label + '，保留原版本供对照。',
                'evidence_refs': [f"{current['definition']['source_context']['kind']}:{current['definition']['source_context']['id']}"]})
    return {'material_changed': bool(items), 'meaningful_items': items[:3]}
