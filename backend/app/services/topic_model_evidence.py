"""Reuse grounded v5.1 model excerpts without promoting model labels to facts."""
from app.services.case_semantic_evidence import SourceText, TextReference

BOUNDARY = ('模型提取仅为已有画像中的待判断候选，引用可核对不等于语义判断已证实。'
            '不混入确定性条件计数，不参与候选评分，不在专题刷新时调用模型。')


def model_evidence(profile, profile_state):
    empty = {'state': 'profile_unavailable', 'items': [], 'boundary': BOUNDARY}
    if profile is None or profile_state not in {'ready', 'partial'}:
        return empty
    try:
        semantics = profile.payload['semantics']
        extraction = semantics.get('model_extraction')
        if extraction is None:
            return {**empty, 'state': 'not_enabled'}
        status = extraction['status']
        if status not in {'ready', 'partial', 'not_enabled', 'unavailable'}:
            raise ValueError('invalid_status')
        result = {**empty, 'state': status, 'version': extraction.get('version'),
                  'coverage': 'selected_excerpts_not_exhaustive'}
        if status not in {'ready', 'partial'}:
            return result
        sources = {item['field']: SourceText(**item) for item in semantics['source_snapshot']['fields']}
        items = extraction['items']
        if not isinstance(items, list) or len(items) > 30:
            raise ValueError('invalid_items')
        checked = []
        for index, item in enumerate(items):
            ref = TextReference(**item['reference'])
            ref.validate(sources[ref.field])
            if (item.get('judgment_status') != 'model_candidate'
                    or item['kind'] not in {'stated', 'negated', 'uncertain'}
                    or item['category'] not in {'action', 'time_condition', 'facility', 'oil', 'tool',
                        'vehicle', 'place_condition', 'upstream_clue', 'downstream_clue'}
                    or item['value'] != ref.quote):
                raise ValueError('invalid_model_candidate')
            checked.append({key: item[key] for key in ('category', 'value', 'kind', 'reference', 'judgment_status')} | {
                'evidence_ref': f'case_profile:{profile.id}:model_candidate:{index}'})
        return {**result, 'items': checked}
    except (KeyError, TypeError, ValueError, AttributeError):
        return {**empty, 'state': 'invalid'}
