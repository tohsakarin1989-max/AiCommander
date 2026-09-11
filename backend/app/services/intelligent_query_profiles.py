"""Read bounded existing semantic profiles; never regenerate or amend case facts."""
from collections import defaultdict

from app.models.case_pipeline import CaseAnalysisProfile
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_search_service import CaseSearchService
from app.services.case_semantic_evidence import SourceText, TextReference, ASSERTION_KINDS


def profile_results(db, args):
    page = CaseSearchService.page(db, **args.model_dump())
    items = []
    groups = defaultdict(set)
    partial = False
    for case in page['items']:
        profile = db.query(CaseAnalysisProfile).filter(
            CaseAnalysisProfile.case_id == case.id, CaseAnalysisProfile.is_current.is_(True)
        ).order_by(CaseAnalysisProfile.profile_version.desc()).first()
        row = {'case_id': case.id, 'case_number': case.case_number,
               'assertions': [], 'information_gaps': [], 'content_state': 'unavailable'}
        items.append(row)
        if profile is None:
            partial = True
            row['information_gaps'] = ['标准画像尚未生成，不代表没有相关线索。']
            continue
        if profile.source_hash != CasePipelineService.source_hash(db, case):
            partial = True
            row['information_gaps'] = ['案件已更新，画像等待后台更新；不使用过期画像描述当前案件。']
            continue
        semantics = (profile.payload or {}).get('semantics') or {}
        row.update(profile_id=profile.id, source_hash=profile.source_hash,
                   profile_version=profile.profile_version, schema_version=profile.schema_version,
                   dictionary_version=profile.dictionary_version, rule_version=semantics.get('rule_version'),
                   evidence_ref=f'case_profile:{profile.id}', content_state='ready')
        try:
            sources = {entry['field']: SourceText(**entry)
                       for entry in semantics.get('source_snapshot', {}).get('fields', [])}
            assertions = semantics.get('assertions', [])
            if not isinstance(assertions, list) or not sources:
                raise ValueError('semantic_sources_missing')
            for assertion in assertions[:100]:
                reference = TextReference(**assertion['reference'])
                reference.validate(sources[reference.field])
                if (assertion['kind'] not in ASSERTION_KINDS or
                        any(not isinstance(assertion.get(key), str) or not assertion[key].strip()
                            for key in ('category', 'value'))):
                    raise ValueError('semantic_kind_invalid')
                row['assertions'].append({key: assertion[key] for key in (
                    'category', 'value', 'kind', 'reference')})
            if len(assertions) > 100:
                row['information_gaps'].append('本案仅返回前100项表述，不视为全部线索。')
                partial = True
                row['content_state'] = 'partial'
        except (KeyError, TypeError, ValueError):
            row['assertions'] = []
            row['content_state'] = 'unavailable'
            row['information_gaps'].append('语义引用未通过原文校验，相关表述暂不返回。')
            partial = True
            continue
        row['potential_conflicts'] = semantics.get('potential_conflicts', [])
        row['information_gaps'].extend(semantics.get('information_gaps', []))
        row['boundary'] = semantics.get('boundary', [])
        for assertion in row['assertions']:
            groups[(assertion['category'], assertion['value'], assertion['kind'])].add(case.id)
    frequencies = [{'category': category, 'value': value, 'kind': kind,
                    'case_count': len(ids), 'case_ids': sorted(ids)}
                   for (category, value, kind), ids in sorted(groups.items())]
    return {'total': page['total'], 'page': page['page'], 'page_size': page['page_size'],
            'items': items, 'batch_patterns': frequencies,
            'next_page': page['page'] + 1 if page['page'] * page['page_size'] < page['total'] else None}, partial
