"""Compare already validated process clauses, never infer a cross-case chain."""
from copy import deepcopy

VERSION = 'history-process-comparison-7.5-1'
PAIR_LIMIT = 24
BOUNDARY = ('只对照已登记画像中的规范化动作及各自原文，不确认共同主体、先后关系或实际链条；'
            '同一片段可能有多项对照，不认定一一对应。共同否定不是行为支持，不确定和反向表述不计为支持。'
            '未记载不等于未发生，历史经验不自动适用于当前案。')


def _side(event, action):
    return {'event_id': event['id'], 'statement_kind': event['statement_kind'],
            'action_kind': action['kind'], 'reference': deepcopy(event['reference']),
            'action_reference': deepcopy(action['reference'])}


def _conditions(event):
    return {(item['category'], item['value'], item['kind']) for item in event['objects']}


def compare_processes(current, historical):
    """Inputs come only from current_semantics' revision/hash/reference checks."""
    a, b = current['process'], historical['process']
    base = {'version': VERSION, 'current': deepcopy(current['source']),
            'historical': deepcopy(historical['source']), 'pairs': [],
            'unmatched_current': [], 'unmatched_historical': [], 'boundary': BOUNDARY}
    if not a or not b:
        return {**base, 'state': 'unavailable', 'reason': '缺少与当前原文修订一致的双侧过程画像，未重新抽取或补造环节。',
                'coverage': {'complete': False, 'pair_limit': PAIR_LIMIT, 'omitted_pairs': 0}}
    pairs, matched_a, matched_b = [], set(), set()
    total_pairs = 0
    by_action = {}
    for event in b['events']:
        for action in event['actions']:
            by_action.setdefault(action['value'], []).append((event, action))
    for event_a in a['events']:
        for action_a in event_a['actions']:
            # Values already use registered canonical labels (e.g. 打眼 → 打孔).
            for event_b, action_b in by_action.get(action_a['value'], []):
                total_pairs += 1
                matched_a.add(event_a['id']); matched_b.add(event_b['id'])
                if len(pairs) >= PAIR_LIMIT:
                    continue  # Count remaining matches without copying unbounded quoted text.
                kinds = {action_a['kind'], action_b['kind']}
                relation = ('counter' if kinds == {'stated', 'negated'} else
                            'stated_match' if kinds == {'stated'} else
                            'negated_match' if kinds == {'negated'} else 'uncertain')
                left, right = _conditions(event_a), _conditions(event_b)
                pairs.append({'action': action_a['value'], 'relation': relation,
                    'current': _side(event_a, action_a), 'historical': _side(event_b, action_b),
                    'shared_conditions': [list(item) for item in sorted(left & right)],
                    'current_only_conditions': [list(item) for item in sorted(left - right)],
                    'historical_only_conditions': [list(item) for item in sorted(right - left)],
                    'counter_conditions': [list(item) for item in sorted(right)
                        if any(item[:2] == other[:2] and {item[2], other[2]} == {'stated', 'negated'} for other in left)],
                    'current_missing_dimensions': list(event_a['missing_dimensions']),
                    'historical_missing_dimensions': list(event_b['missing_dimensions'])})
    def unmatched(process, matched):
        return [{'event_id': event['id'], 'actions': [{'value': action['value'], 'kind': action['kind']}
                 for action in event['actions']], 'reference': deepcopy(event['reference'])}
                for event in process['events'] if event['id'] not in matched]
    omitted = max(0, total_pairs - PAIR_LIMIT)
    complete = not omitted and all(process['coverage']['state'] == 'rule_scan_complete' for process in (a, b))
    return {**base, 'state': 'ready' if complete else 'partial', 'pairs': pairs[:PAIR_LIMIT],
            'unmatched_current': unmatched(a, matched_a), 'unmatched_historical': unmatched(b, matched_b),
            'reason': '按相同规范化动作逐片段对照，不跨句继承油品、地点或主体。' if pairs else '两侧已有片段未发现可对应动作，保留未匹配环节。',
            'coverage': {'complete': complete, 'pair_limit': PAIR_LIMIT, 'omitted_pairs': omitted}}
