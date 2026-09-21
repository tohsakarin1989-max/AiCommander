"""Bounded historical context from the existing v5.1 index, not a second analysis.

The topic census and background retrieval deliberately have separate populations.
Only a small set of representative conditions seeds the latter; it is not an AND
query or a claim that every member has the same historical reference.
"""
from app.services.case_history_retrieval import CaseHistoryRetrieval
from app.services.intelligent_query_history import validate_history_query_evidence


BOUNDARY = ('历史参考独立检索全部授权历史，不套用本期时间窗；按代表条件召回，不等于专题条件的精确匹配。'
            '已统计案件不重复列为历史案件参考，其已确认经验仍可引用。'
            '最多展示三项，不能代表历史总体。相似条件不是当前案件事实；已确认经验仍须核对差异和适用边界。')


def freeze_history(db, aggregate, args, *, deadline):
    patterns = sorted(aggregate['patterns'], key=lambda row: (
        -row['case_count'], row['category'], row['value'], row['kind']))
    explicit = [item.model_dump() for item in args.conditions]
    candidates = explicit if explicit else patterns
    seeds = []
    for item in candidates:
        if item.get('value') and item['kind'] in {'stated', 'negated', 'uncertain'}:
            seed = {key: item[key] for key in ('category', 'value', 'kind')}
            if seed not in seeds:
                seeds.append(seed)
        if len(seeds) >= 8:
            break
    selected = {'conditions': seeds, 'selection': 'saved_conditions' if explicit else 'frequent_profile_conditions',
                'available_condition_count': len(candidates), 'condition_limit': 8}
    if not seeds and not args.keyword:
        return {'state': 'insufficient_conditions', 'selection': selected, 'result': None, 'boundary': BOUNDARY}
    query = args.keyword or '；'.join(item['value'] for item in seeds)
    filters = {'operational_area_id': args.operational_area_id} if args.operational_area_id is not None else {}
    result = CaseHistoryRetrieval.search(db, query=query[:2000], filters=filters, limit=3,
        reuse_only=True, query_conditions={(item['category'], item['value'], item['kind']) for item in seeds},
        deadline=deadline, exclude_case_sources={item['case_id'] for item in aggregate['source_manifest']})
    # Refresh time is not a material change. The enclosing snapshot records it.
    result.pop('generated_at', None)
    return {'state': result['state'], 'selection': selected, 'result': result, 'boundary': BOUNDARY}


def validate_history(db, history):
    if history and history.get('result') is not None:
        validate_history_query_evidence(db, {'cards': [{'tool': 'find_history', 'data': history['result']}]})
    return history
