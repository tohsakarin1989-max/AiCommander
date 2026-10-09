"""Three bounded, local business answers. Query text is data, never a plan.

Persisted answers retain source fingerprints. Reading/exporting a snapshot
checks current permissions and versions, without rerunning its analysis.
"""
from datetime import datetime, timezone
import hashlib
import json
import time
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter

from app.agent_runtime.execution_contract import ExecutionBudget, ExecutionCancelled, ExecutionUsage, sql_budget
from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import OperationalArea, MapSnapshot
from app.services.intelligent_query_history import validate_history_query_evidence
from app.services.business_query_budget import bind as bind_budget, check as check_budget


QuestionType = Literal['case_history', 'attention', 'recent_changes']
VERSION = 'business-answer-8.4-1'
BOUNDARY = '回答仅针对当前授权资料；相似、邻近、条件参考不等于实际涉案或正式事实，不生成执法任务。'


class SourceContext(BaseModel):
    model_config = ConfigDict(extra='forbid')
    case_id: int | None = Field(default=None, gt=0, strict=True)
    asset_id: int | None = Field(default=None, gt=0, strict=True)
    area_id: int | None = Field(default=None, gt=0, strict=True)
    time_basis: Literal['discovery', 'incident', 'entry'] = 'discovery'
    period: Literal['daily', 'weekly'] = 'daily'
    as_of: AwareDatetime | None = None


class ClarificationReply(BaseModel):
    model_config = ConfigDict(extra='forbid')
    clarification_id: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=8, max_length=100)
    value: int = Field(gt=0, strict=True)


def _hash(row):
    ignored = {'is_current', 'updated_at'} if isinstance(row, CaseAnalysisProfile) else set()
    if row.__table__.name == 'evidence_objects':
        ignored.add('content')  # Never read/copy deferred evidence bytes for metadata checks.
    if isinstance(row, MapSnapshot):
        ignored = {'status', 'published_at', 'superseded_at'}  # Historical base remains readable after publication.
    values = {column.key: getattr(row, column.key) for column in row.__table__.columns if column.key not in ignored}
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def _case_versions(db, cases):
    from app.services.case_source_service import CaseSourceService, encode
    # Intake time is a statistical source; quality/features/updated_at are not.
    versions = {}
    for offset in range(0, len(cases), 100):
        check_budget(db)
        batch = cases[offset:offset + 100]
        payloads = CaseSourceService.source_payloads(db, batch)
        for index, row in enumerate(batch):
            if index % 25 == 0:
                check_budget(db)
            versions[row.id] = hashlib.sha256(encode({'source': payloads[row.id], 'created_at': row.created_at}).encode()).hexdigest()
        check_budget(db)
    return versions


def normalize_context(db, question_type, context=None):
    TypeAdapter(QuestionType).validate_python(question_type)
    result = SourceContext.model_validate(context or {}).model_dump(mode='json', exclude_none=True)
    result.setdefault('as_of', datetime.now(timezone.utc).isoformat())
    areas = set()
    for field, model in (('case_id', Case), ('asset_id', JurisdictionAsset)):
        if field in result:
            row = db.query(model).populate_existing().filter(model.id == result[field]).first()
            if row is None:
                raise PermissionError('business_answer_source_unavailable')
            areas.add(row.operational_area_id)
    if len(areas) > 1:
        raise ValueError('business_answer_context_conflict')
    if 'area_id' in result and areas and result['area_id'] not in areas and question_type != 'case_history':
        raise ValueError('business_answer_context_conflict')
    if areas and 'area_id' not in result:
        result['area_id'] = next(iter(areas))
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('business_answer_scope_required')
    allowed = db.info['authorized_area_ids']
    active = db.query(OperationalArea).filter(OperationalArea.status == 'active')
    if allowed is not None:
        active = active.filter(OperationalArea.id.in_(allowed))
    visible = {row.id for row in active}
    if 'area_id' in result and result['area_id'] not in visible:
        raise PermissionError('business_answer_area_unavailable')
    if 'area_id' not in result and len(visible) == 1:
        result['area_id'] = next(iter(visible))
    return result


def missing_context(question_type, context):
    if question_type == 'case_history' and not context.get('case_id'):
        return 'case_id', '请指定要查找历史参考的那条记录。'
    if not context.get('area_id'):
        return 'area_id', '你要了解哪个已授权区域？'
    return None


def source_binding(db, context):
    result = {}
    for field, model in (('case_id', Case), ('asset_id', JurisdictionAsset)):
        if context.get(field):
            row = db.query(model).populate_existing().filter(model.id == context[field]).first()
            if row is None:
                raise PermissionError('business_answer_source_unavailable')
            result[field] = {'id': row.id, 'version': _case_versions(db, [row])[row.id] if model is Case else _hash(row)}
    return result


def _manifest(db, context, *, all_area=False):
    cases = db.query(Case)
    cases = cases.filter(Case.operational_area_id == context['area_id']) if all_area else cases.filter(Case.id == context.get('case_id'))
    rows = []
    for row in cases.populate_existing().order_by(Case.id).yield_per(100):
        if len(rows) % 100 == 0:
            check_budget(db)
        rows.append(row)
    cases = rows
    versions = _case_versions(db, cases)
    entries = [{'kind': 'case', 'id': row.id, 'version': versions[row.id]} for row in cases]
    if all_area:
        for row in db.query(CaseAnalysisProfile).join(Case, Case.id == CaseAnalysisProfile.case_id).filter(
                Case.operational_area_id == context['area_id'], CaseAnalysisProfile.is_current.is_(True)
                ).populate_existing().order_by(CaseAnalysisProfile.id):
            check_budget(db, poll=False)
            entries.append({'kind': 'case_profile', 'id': row.id, 'version': _hash(row)})
    return entries


def _input_guard(db, question_type, context):
    """Reject a read-committed source change between calculation and freezing."""
    if question_type == 'case_history':
        # Historical hits have their own per-fragment source/version validator.
        return source_binding(db, context)
    values = _manifest(db, context, all_area=True)
    if question_type == 'attention':
        from app.models.map_foundation import MapSource
        for kind, model in (('asset', JurisdictionAsset), ('map_source', MapSource)):
            for row in db.query(model).filter(model.operational_area_id == context['area_id']).populate_existing().order_by(model.id):
                check_budget(db, poll=False)
                values.append({'kind': kind, 'id': row.id, 'version': _hash(row)})
    return values


def _refs(value):
    """Collect explicit reference fields only, never parse narrative text."""
    result = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'evidence_refs' and isinstance(item, list):
                result.update(ref for ref in item if isinstance(ref, str))
            elif isinstance(item, (dict, list)):
                result.update(_refs(item))
    elif isinstance(value, list):
        for item in value:
            result.update(_refs(item))
    return result


def _attention_models():
    from app.models.case_source import CaseLocation, CaseSourceLink, CaseRevision, SourceReference, EvidenceObject, DomainChange
    from app.models.case_facility_association import CaseFacilityAssociation
    from app.models.event import Event
    from app.models.map_foundation import MapFeatureClaim, MapSource, JurisdictionAssetVersion, MapFieldDecision, MapSnapshotFeature
    from app.models.user import AuditLog
    return {'case': Case, 'case_profile': CaseAnalysisProfile, 'asset': JurisdictionAsset,
            'case_location': CaseLocation, 'case_source_link': CaseSourceLink, 'event': Event,
            'case_facility_association': CaseFacilityAssociation, 'map_claim': MapFeatureClaim,
            'map_source': MapSource, 'asset_version': JurisdictionAssetVersion, 'map_field_decision': MapFieldDecision,
            'case_revision': CaseRevision, 'source_reference': SourceReference, 'evidence_object': EvidenceObject,
            'domain_change': DomainChange, 'audit_log': AuditLog, 'map_snapshot': MapSnapshot,
            'map_feature': MapSnapshotFeature, 'area': OperationalArea}


def _attention_bindings(db, data, context):
    models = _attention_models()
    entries = _manifest(db, context, all_area=True)
    for kind in ('case_facility_association', 'case_source_link', 'case_location'):
        model = models[kind]
        for row in db.query(model).join(Case, Case.id == model.case_id).filter(
                Case.operational_area_id == context['area_id']).populate_existing():
            entries.append({'kind': kind, 'id': row.id, 'version': _hash(row)})
    references = _refs(data) | {f"asset:{identifier}" for identifier in data.get('source_bindings', {}).get('asset_ids', [])}
    for ref in sorted(references):
        kind, _, identifier = ref.partition(':')
        model = models.get(kind)
        if kind == 'case' and any(entry['kind'] == kind and str(entry['id']) == identifier for entry in entries):
            continue
        if model is None:
            # The complete typed source records below remain the authority;
            # unknown reference forms must not silently certify an answer.
            raise ValueError('business_answer_unknown_evidence')
        row = db.query(model).populate_existing().filter(model.id == identifier).first()
        if row is None:
            raise PermissionError('business_answer_evidence_unavailable')
        entries.append({'kind': kind, 'id': row.id,
                        'version': _case_versions(db, [row])[row.id] if model is Case else _hash(row)})
        if kind == 'source_reference' and row.evidence_object_id:
            obj = db.query(models['evidence_object']).filter_by(id=row.evidence_object_id).first()
            if obj is None:
                raise PermissionError('business_answer_evidence_unavailable')
            entries.append({'kind': 'evidence_object', 'id': obj.id, 'version': _hash(obj)})
    return entries


def validate_answer(db, result):
    answer = (result or {}).get('answer') or {}
    if answer.get('schema_version') != VERSION:
        return
    context = normalize_context(db, answer['question_type'], answer['time_scope_versions']['source_context'])
    manifest = result.get('source_manifest') or []
    for kind in {entry['kind'] for entry in manifest}:
        check_budget(db)
        model = _attention_models().get(kind)
        if model is None:
            raise PermissionError('business_answer_evidence_changed')
        bindings = [entry for entry in manifest if entry['kind'] == kind]
        for offset in range(0, len(bindings), 400):
            check_budget(db)
            batch = bindings[offset:offset + 400]
            query = db.query(model).populate_existing().filter(model.id.in_([item['id'] for item in batch]))
            if kind == 'audit_log':
                query = query.filter(model.detail['operational_area_id'].as_integer() == context['area_id'])
            rows = query.all()
            versions = _case_versions(db, rows) if model is Case else {}
            if model is not Case:
                for row in rows:
                    check_budget(db, poll=False)
                    versions[row.id] = _hash(row)
            if any(versions.get(item['id']) != item['version'] for item in batch):
                raise PermissionError('business_answer_evidence_changed')
    validate_history_query_evidence(db, result)
    for card in result.get('cards', []):
        if card.get('tool') == 'business_attention':
            from app.services.attention_grounding import attention_sources_visible
            if not attention_sources_visible(db, card['data']):
                raise PermissionError('business_answer_attention_changed')
    # The context check also protects an empty answer with no source manifest.
    if context['area_id'] != answer['time_scope_versions']['source_context']['area_id']:
        raise PermissionError('business_answer_scope_changed')


def _history(db, context, history_area_filter=None):
    from app.services.case_history_retrieval import CaseHistoryRetrieval
    # The area's purpose here is identifying the source case. It is not a
    # silent same-area restriction on the user's authorized historical corpus.
    data = CaseHistoryRetrieval.case_references(db, source_case_id=context['case_id'],
        filters={'operational_area_id': history_area_filter} if history_area_filter is not None else None)
    items = data['items']
    evidence = [{'text': item.get('title') or item.get('snippet') or '历史参考',
                 'evidence_refs': sorted(_refs(item)) or [f"case:{item['case_id']}"],
                 'source': item} for item in items]
    differences = [{'text': '明确差异对照，不作为正向匹配。' if item.get('purpose') == 'contrast' else '相似不等于当前事实。',
                    'conditions': item.get('different_conditions', []),
                    'evidence_refs': sorted(_refs(item)) or [f"case:{item['case_id']}"],
                    'contrast_evidence': item.get('contrast_evidence')} for item in items]
    complete = data.get('coverage', {}).get('complete', False)
    gaps = list(data.get('information_gaps', []))
    if not complete:
        gaps.append('历史索引或扫描覆盖尚不完整；未命中不能解释为全库没有参考。')
    if data.get('degraded'):
        gaps.append('本地语义增强未启用或不可用；当前参考采用已有结构及词项依据。')
    status = ('answered' if complete else 'partial') if items else 'insufficient_data'
    scope = '指定授权区域历史' if history_area_filter is not None else '当前全部授权历史'
    direct = f"在{scope}中找到 {len(items)} 项可核对的参考，已区分相似条件和关键差异；不自动认定当前案件关系。" if items else '现有授权资料未形成有依据的历史参考，不能据此认定没有相似情况。'
    return 'find_history', data, direct, evidence, differences, gaps, status, _manifest(db, context)


def _attention(db, context):
    from app.services.attention_grounding import build_attention_grounding, facility_attention_grounding
    from app.services.facility_condition_comparison import profile_catalog
    from app.services.facility_dossier_content import _production
    from app.services.situation_temporal_changes import closed_window, membership, time_range
    window = closed_window(datetime.fromisoformat(context['as_of']), context['period'])
    cases = db.query(Case).filter(Case.operational_area_id == context['area_id']).order_by(Case.id).all()
    cases = [row for row in cases if membership(time_range(row, context['time_basis']), window.current_start, window.current_end) == 'included']
    if context.get('asset_id'):
        asset = db.query(JurisdictionAsset).filter_by(id=context['asset_id']).one()
        records, coverage = profile_catalog(db, cases)
        item = facility_attention_grounding(db, asset, cases, records, coverage, production=_production(db, asset)[0])
        data = {'version': item['version'], 'items': [item], 'coverage': item['coverage'],
                'source_bindings': {'case_ids': [row.id for row in cases], 'asset_ids': [asset.id]}, 'boundary': item['boundary']}
    else:
        area = db.query(OperationalArea).filter_by(id=context['area_id']).one()
        data = build_attention_grounding(db, area.id, [row.id for row in cases], area_name=area.name)
    data['time_window'] = {'start': window.current_start.isoformat(), 'end': window.current_end.isoformat(), 'basis': context['time_basis']}
    items = data['items']
    evidence = [{'text': item['label'], 'evidence_refs': item['evidence_refs'], 'layers': item['layers']} for item in items]
    differences = [{'text': item['boundary'], 'evidence_refs': item['evidence_refs']} for item in items]
    gaps = sorted({gap for item in items for gap in item['gaps']})
    gaps.append('时间未知或跨期记录不推入本期；资料缺失不等于现实中不存在。')
    supported = [item for item in items if item['state'] != 'background_only']
    completeness = 'partial' if items else 'insufficient_data'
    gaps.extend(data.get('coverage', {}).get('information_gaps', []))
    if (supported and data.get('coverage', {}).get('state') != 'partial'
            and not any(data.get('coverage', {}).get(key, 0) for key in
                             ('profiles_stale', 'profiles_missing', 'profiles_invalid', 'profiles_partial'))):
        completeness = 'answered'
    direct = (f"本期找到 {len(supported)} 项关注依据；明确关联、邻近背景和条件相似分层展示，不形成风险评分。"
              if supported else '当前资料只支持背景说明或尚无足够关注依据，不据此判断低风险或没有问题。')
    return 'business_attention', data, direct, evidence, differences, gaps, completeness, _attention_bindings(db, data, context)


def _changes(db, context):
    from app.services.situation_temporal_changes import case_changes, closed_window
    data = case_changes(db, context['area_id'], closed_window(datetime.fromisoformat(context['as_of']), context['period']), context['time_basis'])
    current, previous, origins = data['current'], data['previous'], data['change_origins']
    refs = [f"case:{row['case_id']}" for row in data['source_manifest']]
    direct = (f"按{data['time_basis_label']}口径，本期登记 {current['case_count']} 起，前期 {previous['case_count']} 起，"
              f"变化 {data['case_count_change']:+d} 起；本期补录历史情况 {origins['late_entry']['count']} 起。登记数量变化不等于发生率变化。")
    evidence = [{'text': '同范围、同长度周期登记数量', 'evidence_refs': refs, 'current': current, 'previous': previous}]
    differences = [{'text': origins['boundary'], 'evidence_refs': refs, 'change_origins': origins}]
    gaps = [data['boundary']]
    time_incomplete = data['quality']['unknown_time_count'] or current['uncertain_count'] or previous['uncertain_count']
    if time_incomplete:
        gaps.append('存在时间未知或跨期记录，实质变化只能部分回答，不能将其强行归入某一天。')
    semantic_incomplete = data['semantic_changes']['state'] != 'comparable'
    if semantic_incomplete:
        gaps.extend(data['semantic_changes'].get('information_gaps', []))
    else:
        semantic = data['semantic_changes']
        terms = {}
        for period in ('previous', 'current'):
            for term in semantic[period]['terms']:
                check_budget(db, poll=False)
                terms.setdefault((term['category'], term['value'], term['kind']), []).extend(term['evidence'])
        categories = {'method': '手法', 'place_condition': '地点条件', 'time_condition': '时间条件'}
        kinds = {'stated': '原文明述（未核实）', 'negated': '原文明示否定',
                 'uncertain': '原文不确定', 'inferred': '派生推断（未确认）'}
        changed = [item for item in semantic['changes'] if item['case_count_change'] != 0]
        changed.sort(key=lambda item: (-abs(item['case_count_change']), item['category'], item['value'], item['kind']))
        for item in changed:
            check_budget(db, poll=False)
            references = terms[(item['category'], item['value'], item['kind'])]
            evidence_refs = sorted({ref for entry in references for ref in
                                    (f"case:{entry['case_id']}", f"case_profile:{entry['profile_id']}")})
            text = (f"{categories[item['category']]}“{item['value']}”的{kinds[item['kind']]}表述涉及记录："
                    f"前期 {item['previous_count']} 起，本期 {item['current_count']} 起，变化 {item['case_count_change']:+d} 起；"
                    '仅是已录入表述差异，不代表现实中该条件新增、消失或已经核实。')
            differences.append({'text': text, 'evidence_refs': evidence_refs,
                                'semantic_change': item, 'references': references})
        if changed:
            examples = '；'.join(f"{categories[item['category']]}“{item['value']}”的{kinds[item['kind']]}表述 "
                                 f"{item['previous_count']}→{item['current_count']} 起" for item in changed[:3])
            direct += f" 已有画像中另有 {len(changed)} 项表述数量变化：{examples}。不将否定、不确定或推断当作肯定事实。"
        else:
            direct += ' 在本次可比较的已有画像范围内，未见手法、地点和时间条件表述数量变化；不等于现实没有变化。'
    status = 'partial' if time_incomplete or semantic_incomplete else 'answered'
    if not data['quality']['denominator']:
        status, direct = 'insufficient_data', '当前授权区域尚无登记资料，不能判断近期实际情况是否发生变化。'
    manifest = _manifest(db, context, all_area=True)
    identifiers = {'case_revision': {row['revision_id'] for row in data['source_manifest'] if row['revision_id']},
                   'domain_change': {row['change_id'] for row in origins['corrections']['items']},
                   'audit_log': set(origins['withdrawals']['audit_ids'])}
    models = _attention_models()
    for kind, values in identifiers.items():
        for identifier in sorted(values):
            row = db.query(models[kind]).filter_by(id=identifier).first()
            if row is None:
                raise PermissionError('business_answer_evidence_unavailable')
            manifest.append({'kind': kind, 'id': row.id, 'version': _hash(row)})
    return 'business_recent_changes', data, direct, evidence, differences, gaps, status, manifest


def run_business_answer(db, question_type, context, *, cancelled, envelope, consumed=None, version_note=None,
                        history_area_filter=None, budget=None):
    consumed = consumed or {'tool_steps': 0, 'active_ms': 0}
    usage = ExecutionUsage()
    remaining = max(0, 120 - consumed['active_ms'] / 1000)
    budget = budget or ExecutionBudget(time.monotonic() + remaining, cancelled=cancelled)
    cards, trace, manifest, evidence, differences = [], [], [], [], []
    map_context = None
    direct, gaps, completeness, error = '依赖服务暂不可用，尚未形成回答。', [], 'service_unavailable', None
    try:
        if consumed['tool_steps'] >= 8 or remaining <= 0:
            raise TimeoutError('business_answer_budget_exhausted')
        with bind_budget(db, budget), sql_budget(db, budget):
            budget.take_step()
            usage.tool_calls += 1
            inputs = _input_guard(db, question_type, context)
            tool, data, direct, evidence, differences, gaps, completeness, manifest = {
                'case_history': lambda db, context: _history(db, context, history_area_filter),
                'attention': _attention, 'recent_changes': _changes,
            }[question_type](db, context)
            if inputs != _input_guard(db, question_type, context):
                raise PermissionError('business_answer_inputs_changed')
            from app.services.business_answer_map import build_map_context
            from sqlalchemy.exc import SQLAlchemyError
            try:
                map_context, map_bindings = build_map_context(db, question_type, context, data)
            except (PermissionError, ExecutionCancelled, TimeoutError, SQLAlchemyError):
                raise
            except Exception:
                # Map formatting/build dependencies are optional; storage or
                # authorization failures are never disguised as safe content.
                map_context, map_bindings = {'schema_version': 'business-answer-map-8.4-1',
                    'state': 'unavailable', 'snapshots': [], 'points': [],
                    'coverage': {'point_limit': 100, 'shown': 0, 'truncated': False},
                    'information_gaps': ['地图资料暂不可用；保留文字答案，不补造点位。'],
                    'boundary': BOUNDARY}, []
            manifest.extend(map_bindings)
            data = {**data, 'map_context': map_context}
            budget.check()
            cards = [{'tool': tool, 'state': 'ready' if completeness == 'answered' else 'partial', 'data': data,
                      'evidence': {'source_context': context, 'algorithm_version': VERSION},
                      'information_gaps': gaps, 'boundary': BOUNDARY}]
            trace = [{'step': consumed['tool_steps'] + 1, 'tool': tool, 'arguments': context,
                      'duration_ms': usage.public()['duration_ms'], 'evidence': sorted(_refs(evidence))}]
    except (PermissionError, ExecutionCancelled):
        return {'status': 'cancelled', 'cards': [], 'trace': [], 'error_code': 'query_access_changed'}
    except Exception as exception:
        db.rollback()
        cards, trace, manifest, evidence, differences = [], [], [], [], []
        map_context = None
        direct, completeness = '依赖服务暂不可用，尚未形成回答。', 'service_unavailable'
        error = 'query_budget_exhausted' if isinstance(exception, TimeoutError) else 'business_answer_service_unavailable'
        gaps = ['本轮未得到可验证结果，请稍后重试；未把失败解释为没有匹配。']
    if version_note:
        gaps.append(version_note)
    public_usage = usage.public()
    answer = {'schema_version': VERSION, 'question_type': question_type, 'direct_answer': direct,
              'evidence': evidence, 'differences': differences, 'unanswered': gaps,
              'time_scope_versions': {'source_context': context, 'algorithm_version': VERSION,
                  'selection': ('explicit_area_history' if history_area_filter is not None else 'all_authorized_history')
                               if question_type == 'case_history' else 'authorized_area_equal_periods',
                  'history_area_filter': history_area_filter,
                  'authorized_area_ids': db.info.get('authorized_area_ids'),
                  'scope_version': envelope.get('scope_version'), 'answered_at': datetime.now(timezone.utc).isoformat(),
                  'source_versions': manifest},
              'completeness': completeness, 'summary': direct, 'information_gaps': gaps,
              'findings': [{'text': row['text'], 'card_index': 0, 'evidence_refs': row['evidence_refs']} for row in evidence],
              'map_context': map_context, 'boundary': BOUNDARY}
    from app.services.question_contract import make_question_spec, unify_answer
    answer = unify_answer(answer, cards, make_question_spec(question_type=question_type, context=context))
    completeness = answer['completeness']
    return {'status': 'completed' if completeness == 'answered' else 'degraded', 'answer': answer,
            'cards': cards, 'trace': trace, 'source_manifest': manifest, 'error_code': error,
            'execution_mode': 'deterministic_business_question', 'task_envelope': envelope,
            'usage': public_usage, 'chain_usage': {'tool_steps': consumed['tool_steps'] + public_usage['tool_calls'],
                'active_ms': consumed['active_ms'] + public_usage['duration_ms']}, 'boundary': BOUNDARY}
