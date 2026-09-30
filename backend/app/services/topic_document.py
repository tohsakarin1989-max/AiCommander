"""Export the selected topic revision, without statistics or model re-execution."""
from itertools import islice

from app.services import analysis_topic_service as topics
from app.services.case_result_document import CaseResultDocument, DocumentBlock
from app.services.case_result_export import render_docx
from app.services.case_result_pdf import _convert_generated_docx
from app.services.document_budget import document_budget
from app.services.intelligent_query_document import LABELS as QUERY_LABELS
from app.services.topic_projections import resolve_references
from app.services.typed_material_document import LABELS as MATERIAL_LABELS, STATES


LABELS = {**MATERIAL_LABELS, **QUERY_LABELS,
    'case_id': '案件编号', 'operational_area_id': '辖区编号', 'conditions': '条件组合',
    'profiles_complete': '画像是否全部就绪', 'profile_state': '画像状态', 'profile_states': '画像状态分布',
    'structural_filters': '登记字段条件', 'model_conditions': '模型提取条件', 'require_complete': '是否要求完整',
    'source_context': '发起来源', 'window': '时间窗口', 'as_of': '统计截止', 'mode': '方式',
    'days': '天数', 'matched': '满足全部条件', 'unmatched': '不同或相反表述',
    'unknown': '资料不足', 'not_scanned': '未遍历', 'eligible_cases': '符合范围案件数',
    'missing_profiles': '缺少画像的案件数', 'stale_profiles': '画像过期的案件数',
    'excluded_linked': '已关联案件而排除的事件数', 'independent_count': '独立事件数',
    'scope_version': '授权范围版本', 'data_version': '数据版本', 'definition_revision': '专题定义版本',
    'reason': '原因', 'source_case_id': '来源案件编号', 'source_revision_id': '原始来源版本',
    'added_case_ids': '新增案件编号', 'removed_case_ids': '移出案件编号',
    'profiles': '画像', 'baseline': '对照基线', 'changed': '是否变化', 'meaningful': '是否实质变化',
    'rules_version': '规则版本', 'dictionary_version': '词典版本', 'start': '原文起始位置', 'end': '原文结束位置',
    'field': '原文字段', 'text_sha256': '原文校验', 'status': '状态', 'case_count': '案件数'}
VALUES = {**STATES, 'stated': '明确陈述', 'negated': '否定陈述', 'uncertain': '不确定陈述',
    'inferred': '推断', 'conflicting': '矛盾陈述', 'method': '作案手法', 'oil': '油品',
    'facility': '设施', 'place_condition': '地点条件', 'time_condition': '时间条件', 'tool': '工具',
    'vehicle': '车辆', 'upstream_clue': '上游线索', 'downstream_clue': '下游线索',
    'rolling': '滚动窗口', 'fixed': '固定窗口', 'all': '全范围', 'invalid': '无效',
    'completed': '已完成', 'degraded': '降级完成', 'missing_profile': '画像未就绪'}


def _rows(value, prefix='', depth=0):
    if depth > 16:
        raise ValueError('topic_document_too_deep')
    if isinstance(value, dict):
        if not value:
            yield (prefix, '未记录')
        for key, item in value.items():
            label = LABELS.get(key, key)
            yield from _rows(item, f'{prefix} / {label}' if prefix else label, depth + 1)
    elif isinstance(value, list):
        if not value:
            yield (prefix, '未记录')
        for index, item in enumerate(value, 1):
            yield from _rows(item, f'{prefix} · {index}', depth + 1)
    else:
        rendered = '未提供' if value is None else ('是' if value else '否') if isinstance(value, bool) else VALUES.get(str(value), str(value))
        yield (prefix, rendered)


def build_topic_document(db, topic_id, revision, *, preview=False):
    topic = topics._owned(db, topic_id)
    snapshot = topics._snapshot(db, topic_id, revision)
    topics.validate_snapshot_access(db, snapshot)
    aggregate = snapshot.payload['aggregate']
    references = resolve_references(db, snapshot.payload.get('references', {}))
    definition = snapshot.payload.get('definition') or {}
    remaining = 4000 if preview else 10000
    blocks = [
        DocumentBlock('heading', '专题研判与周期材料'),
        DocumentBlock('paragraph', f"专题名称：{definition.get('title', topic.title)}；引用成果第 {revision} 版。"),
        DocumentBlock('paragraph', f"持续关注问题：{definition.get('question', topic.title)}"),
        DocumentBlock('paragraph', '这是冻结成果，不重新抽取案情或计算道路。分析案组不等于正式串并案、真实团伙或已经认定的事实。'),
        DocumentBlock('table', '成果版本', (
            ('成果编号', snapshot.id), ('内容校验', snapshot.content_sha256),
            ('形成时间', snapshot.created_at.isoformat()),
        )),
    ]
    def table(title, value):
        nonlocal remaining
        limit = min(remaining, 800) if preview else remaining
        rows = list(islice(_rows(value), limit + 1))
        overflow = len(rows) > limit
        if overflow and not preview:
            raise ValueError('topic_document_too_large')
        blocks.append(DocumentBlock('table', title, tuple(rows[:limit])))
        remaining -= min(len(rows), limit)
        if overflow:
            blocks.append(DocumentBlock('paragraph', f'阅读概览：{title}仅展开前 {limit} 个字段行；其余仍在本版冻结成果中，可在专题分页查看，不表示不存在。总体统计不受此展示上限影响。'))
    table('冻结筛选条件', definition.get('resolved_filters', aggregate.get('filters', {})))
    for title, key in [('授权集合与扫描完整度', 'coverage'), ('总体统计', 'statistics'),
                       ('条件分布（按案件去重）', 'patterns'), ('表述缺失比例及分母', 'missingness'),
                       ('已有模型提取状态（候选，不计入条件统计）', 'model_extraction'),
                       ('匹配案组来源', 'members'), ('不同或相反表述来源', 'counterexamples'),
                       ('资料不足来源', 'unknown')]:
        value = aggregate.get(key, [])
        if key == 'patterns':
            value = [{k: v for k, v in item.items() if k != 'case_ids'} for item in value]
        table(title, value)
    table('独立事件补充（不与案件相加）',
        {key: value for key, value in snapshot.payload['events'].items() if key != 'source_manifest'})
    table('与上一成果的变化', snapshot.changes)
    if snapshot.payload.get('case_context'):
        case = snapshot.payload['case_context']
        saved = (case.get('profile') or {}).get('data') or {}
        body = saved.get('payload') or {}
        from app.services.case_process_document import process_blocks
        table('本案已有资料与缺口',
            {key: body.get(key) for key in ('quality', 'analysis_readiness', 'information_gaps')})
        process = (body.get('semantics') or {}).get('process')
        if process:
            blocks.extend(process_blocks(process))
    if snapshot.payload.get('facility_context'):
        context = snapshot.payload['facility_context']
        table('所关注设施', context['facility'])
        section_labels = {'production': '生产台账', 'record_links': '明确记录关联', 'nearby_cases': '空间邻近案件',
            'candidate_links': '候选关联', 'events': '独立事件', 'results': '已有成果', 'roads': '道路与入口',
            'tech_defense': '技防登记', 'history_conditions': '历史条件'}
        for key, section in context['sections'].items():
            table(f'设施分类资料：{section_labels.get(key, key)}', section)
    if references['history'] is not None:
        table('历史案件与已确认经验（独立参考，不计入本期统计）', references['history'])
    for title, key in [('已有案件候选及反向依据', 'case_results'), ('已有道路依据', 'roads'),
                       ('同辖区既有日/周材料', 'briefs'), ('地图版本引用', 'maps')]:
        table(title, references[key])
    blocks.append(DocumentBlock('paragraph',
        '日/周材料只作同辖区背景，未套用专题语义条件，不与专题统计合并。地图沿用上述版本；'
        '未生成未核验的道路示意图。原文依据可用本版专题的案件画像引用回查。'
        '缺少表述不等于现实中不存在，未知不得当作否定。'))
    if not preview and sum(len(block.rows) for block in blocks) > 10000:
        raise ValueError('topic_document_too_large')
    return CaseResultDocument('topic-document-5.3-1', snapshot.id, snapshot.content_sha256, tuple(blocks))


@document_budget
def export_topic_document(db, topic_id, revision, format):
    if format not in {'docx', 'pdf'}:
        raise ValueError('topic_document_format')
    document = build_topic_document(db, topic_id, revision)
    data = render_docx(document)
    if format == 'pdf':
        data = _convert_generated_docx(data)
    db.expire_all()
    latest = topics.read_topic(db, topic_id, revision=revision)['snapshot']
    if latest['content_sha256'] != document.content_sha256:
        raise PermissionError('topic_document_changed')
    return document, data
