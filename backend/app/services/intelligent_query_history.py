"""历史参考进入模型上下文、保存、读取、追问与导出前的当前来源复核。"""
import json

from sqlalchemy import select

from app.models.case import Case
from app.models.knowledge_asset import KnowledgeAsset
from app.services.case_history_retrieval import _asset_access, source_values
from app.services.case_history_index_service import content_hash
from app.services.case_semantic_evidence import freeze_sources, snapshot_payload, text_hash


def _case(db, identifier):
    if type(identifier) is not int or identifier <= 0:
        raise ValueError('invalid_case_reference')
    case = db.scalar(select(Case).where(Case.id == identifier).execution_options(populate_existing=True))
    if case is None:
        raise ValueError('missing_case_reference')
    return case


def _source_hash(case):
    return snapshot_payload(freeze_sources(source_values(case)))['sha256']


def validate_history_query_evidence(db, result):
    for card in (result or {}).get('cards', []):
        if card.get('tool') != 'find_history':
            continue
        try:
            if 'authorized_area_ids' not in db.info:
                raise ValueError('missing_scope')
            data = card['data']
            if data['schema_version'] != 'case-history-5.1-1' or not isinstance(data['items'], list):
                raise ValueError('invalid_history_contract')
            source = data.get('source_case_id')
            if source is not None and _source_hash(_case(db, source)) != data['query_context']['source_text_hash']:
                raise ValueError('source_changed')
            for item in data['items']:
                case = _case(db, item['case_id'])
                versions = item['versions']
                if item['source_type'] == 'case':
                    if item['source_id'] != case.id or versions['source_text_hash'] != _source_hash(case):
                        raise ValueError('case_changed')
                elif item['source_type'] == 'experience_card':
                    asset = db.scalar(select(KnowledgeAsset).where(KnowledgeAsset.id == item['source_id'],
                        KnowledgeAsset.source_case_id == case.id, KnowledgeAsset.asset_type == 'experience_card')
                        .execution_options(populate_existing=True))
                    if (asset is None or asset.status != 'confirmed' or not _asset_access(db, asset)
                            or asset.version != versions['asset_version']
                            or asset.source_signature != versions['source_signature']
                            or content_hash(asset.content if isinstance(asset.content, dict) else {}) != versions['content_hash']
                            or text_hash(json.dumps(asset.evidence_refs, sort_keys=True, ensure_ascii=False)) != versions['evidence_refs_hash']):
                        raise ValueError('experience_changed')
                elif item['source_type'] == 'legacy_experience_card':
                    legacy = ((case.features or {}).get('intelligence') or {}).get('experience_card') or {}
                    dedicated = db.scalar(select(KnowledgeAsset.id).where(KnowledgeAsset.source_case_id == case.id,
                        KnowledgeAsset.asset_type == 'experience_card').limit(1))
                    if (dedicated is not None or item['source_id'] != case.id
                            or legacy.get('manual_review_status') != 'confirmed'
                            or content_hash(legacy) != versions['content_hash']):
                        raise ValueError('legacy_experience_changed')
                else:
                    raise ValueError('unknown_history_source')
        except (KeyError, TypeError, AttributeError, ValueError) as error:
            raise PermissionError('query_history_evidence_changed') from error
