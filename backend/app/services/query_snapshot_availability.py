"""Historical business answers stay frozen, but never bypass current authority.

Only newly published, strictly validated answers receive this receipt. Legacy
answers are not retroactively certified from today's rows. The receipt binds
the actual frozen answer/cards to typed source identities and original areas.
It is an integrity receipt, not a substitute for a database access decision.
"""
from app.models.case import Case
from app.models.knowledge_asset import KnowledgeAsset
from app.services.business_answer import _attention_models, _case_versions, _hash
from app.services.intelligent_query_context import result_hash


VERSION = 'query-frozen-sources-9.2-1'


def _models():
    return {**_attention_models(), 'knowledge_asset': KnowledgeAsset}


def _material(result):
    return {key: result.get(key) for key in ('answer', 'cards', 'source_manifest')}


def freeze_validated_business_snapshot(db, result):
    answer = result.get('answer') or {}
    if (answer.get('answer_contract_version') != 'answer-snapshot-9.3-1'
            or not answer.get('question_type') or not result.get('cards')):
        return result
    entries = {(item['kind'], item['id']): dict(item) for item in result.get('source_manifest', [])}
    legacy = set()
    for card in result['cards']:
        if card.get('tool') != 'find_history':
            continue
        for item in card['data'].get('items', []):
            entries.setdefault(('case', item['case_id']), {'kind': 'case', 'id': item['case_id']})
            if item.get('source_type') == 'experience_card':
                entries.setdefault(('knowledge_asset', item['source_id']), {
                    'kind': 'knowledge_asset', 'id': item['source_id']})
            elif item.get('source_type') == 'legacy_experience_card':
                legacy.add(item['case_id'])
    bindings = []
    models = _models()
    for entry in entries.values():
        model = models.get(entry['kind'])
        if model is None:
            raise PermissionError('query_snapshot_source_unknown')
        row = db.query(model).populate_existing().filter(model.id == entry['id']).first()
        if row is None:
            raise PermissionError('query_snapshot_source_unavailable')
        value = _case_versions(db, [row])[row.id] if model is Case else _hash(row)
        if entry.get('version') and value != entry['version']:
            raise PermissionError('query_snapshot_source_changed')
        area = getattr(row, 'operational_area_id', None)
        case_id = getattr(row, 'case_id', None) or getattr(row, 'source_case_id', None)
        if case_id is not None:
            case = db.query(Case).filter_by(id=case_id).first()
            if case is None:
                raise PermissionError('query_snapshot_source_unavailable')
            area = case.operational_area_id
        bindings.append({**entry, 'version': value, 'area_id': area,
            **({'case_id': case_id} if case_id is not None else {}),
            **({'legacy_confirmation': True} if entry['kind'] == 'case' and entry['id'] in legacy else {})})
    result['frozen_source_receipt'] = {'schema_version': VERSION, 'bindings': bindings,
        'content_sha256': result_hash(_material(result)),
        'validated_at': answer['time_scope_versions']['answered_at'],
        'boundary': '仅证明生成时严格验证且保存了本次引用内容；当前读取仍核验源存在、撤回状态和权限。'}
    return result


def snapshot_availability(db, result):
    receipt = (result or {}).get('frozen_source_receipt')
    if not receipt:
        return None
    if ('authorized_area_ids' not in db.info or receipt.get('schema_version') != VERSION
            or receipt.get('content_sha256') != result_hash(_material(result))):
        raise PermissionError('query_snapshot_incomplete')
    allowed, changed = db.info['authorized_area_ids'], []
    models = _models()
    for card in result.get('cards', []):
        if card.get('tool') == 'business_attention':
            from app.services.attention_grounding import attention_sources_visible
            if not attention_sources_visible(db, card['data']):
                raise PermissionError('query_snapshot_restricted')
    for entry in receipt.get('bindings', []):
        model = models.get(entry['kind'])
        if model is None:
            raise PermissionError('query_snapshot_incomplete')
        if entry.get('area_id') is not None and allowed is not None and entry['area_id'] not in allowed:
            raise PermissionError('query_snapshot_restricted')
        row = db.query(model).populate_existing().filter(model.id == entry['id']).first()
        if row is None:
            raise PermissionError('query_snapshot_source_withdrawn')
        area = getattr(row, 'operational_area_id', None)
        if entry.get('case_id') is not None:
            case = db.query(Case).populate_existing().filter_by(id=entry['case_id']).first()
            if case is None:
                raise PermissionError('query_snapshot_source_withdrawn')
            area = case.operational_area_id
        if area != entry.get('area_id'):
            raise PermissionError('query_snapshot_restricted')
        if (getattr(row, 'availability', None) == 'revoked'
                or getattr(row, 'status', None) in {'revoked', 'withdrawn', 'deleted'}):
            raise PermissionError('query_snapshot_source_withdrawn')
        if isinstance(row, KnowledgeAsset):
            from app.services.case_history_retrieval import _asset_access
            if row.status != 'confirmed' or not _asset_access(db, row):
                raise PermissionError('query_snapshot_source_withdrawn')
        if entry.get('legacy_confirmation'):
            if (((row.features or {}).get('intelligence') or {}).get('experience_card') or {}).get('manual_review_status') != 'confirmed':
                raise PermissionError('query_snapshot_source_withdrawn')
        version = _case_versions(db, [row])[row.id] if model is Case else _hash(row)
        if version != entry['version']:
            changed.append({'kind': entry['kind'], 'id': entry['id'], 'frozen_version': entry['version'],
                            'current_version': version})
    return {'state': 'historical' if changed else 'current', 'as_of': receipt['validated_at'],
        'changed_sources': changed,
        'message': '部分来源已正常更正；以下仍为生成时冻结内容，不代表最新资料。' if changed else
                   '本次冻结引用来源仍可核对；未重新运行分析。'}
