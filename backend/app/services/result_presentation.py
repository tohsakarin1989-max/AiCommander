"""Pure presentation of authorized frozen materials; no queries or inference."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime
import re

from fastapi.encoders import jsonable_encoder

from app.services.case_result_document import CaseResultDocument, DocumentBlock
from app.services.typed_material_document import LABELS, text


SCHEMA = 'material-presentation-9.4-1'
KIND_LABELS = {'case': '案件成果', 'topic': '专题材料', 'facility': '设施材料',
    'situation': '态势简报', 'meeting': '会议报告', 'query': '助手查询',
    'experience': '经验与历史报告', 'conclusion': '历史结论'}
TEMPLATES = {'full': '完整资料', 'case_summary': '案件资料摘要',
    'facility_sheet': '设施资料单', 'period_brief': '周期情况材料'}
PER_KIND = {'case': 'case_summary', 'facility': 'facility_sheet', 'situation': 'period_brief'}
BOUNDARY = '通用整理格式，不是单位正式样表；仅排布本材料的冻结记录，不重新分析。办公软件中的修改不会写回原始事实。'
SECTIONS = {'facts': '事实与记录', 'evidence': '支持依据', 'differences': '差异与反向情况',
    'gaps': '资料缺口', 'boundary': '适用边界', 'map': '同源地图'}
SECTIONS_BOUNDARY = '章节选择仅调整已冻结资料的呈现。必要证据引用、时间版本与适用边界始终保留；候选解释所需的支持、反向情况和资料缺口不会隐藏。未识别为可省略的旧章节仍完整保留。'


def validate_sections(sections=None):
    if sections is None:
        return list(SECTIONS)
    if (not isinstance(sections, (list, tuple)) or not 1 <= len(sections) <= len(SECTIONS)
            or any(not isinstance(key, str) or key not in SECTIONS for key in sections)
            or len(set(sections)) != len(sections)):
        raise ValueError('invalid_material_sections')
    return [key for key in SECTIONS if key in sections]


def _section_projection(result, document, sections):
    selected = validate_sections(sections)
    # Conservative allowlist: an unrecognized historical heading is never
    # silently dropped. Candidate sections and mandatory qualifications stay
    # together; selecting fewer chapters cannot turn a hypothesis into a fact.
    optional = {'事实摘要与关联条件': 'facts', '案情语义画像与原文引用': 'facts',
        '本单位处置及已知反馈': 'facts', '周期摘要': 'facts', '冻结的等长周期对照': 'differences',
        '生产与来源': 'facts', '设施登记资料': 'facts'}
    protected = {'关键缺项', '待核验候选', '分析信息缺口', '整份资料缺口', '版本与适用边界',
        '支持证据', '反向证据', '信息缺口', '可打开的冻结来源', '本材料版本',
        '统计口径', '算法与形成时间', '未知与缺口', '资料适用范围与分析状态'}
    blocks, current = [], None
    for block in document.blocks:
        if block.kind == 'heading':
            current = optional.get(block.text)
            if block.text in protected:
                current = None
        elif block.kind == 'table' and block.text in protected:
            current = None
        if block.kind == 'map':
            if 'map' in selected:
                blocks.append(block)
            continue
        if block.kind == 'source' or current is None or current in selected:
            blocks.append(block)
    identity = jsonable_encoder(result)
    leading = [DocumentBlock('paragraph', SECTIONS_BOUNDARY), DocumentBlock('source',
        f'材料：{identity["kind"]}/{identity["id"]}；形成时间：{identity["created_at"]}；内容版本：{identity["content_sha256"]}；章节：{",".join(selected)}')]
    trailing = [DocumentBlock('paragraph', value) for value in result.get('boundary', [])]
    return replace(document, schema=f'{SCHEMA}/sections', blocks=tuple(leading + blocks + trailing))


def _period_change_blocks(result):
    """Expose existing frozen explanations, not a new period calculation."""
    snapshot = result['body'].get('comparison_snapshot') or {}
    origins = snapshot.get('change_origins') or {}
    changes = snapshot.get('snapshot_change') or {}
    blocks = [DocumentBlock('heading', '本材料已保存的变化清单'), DocumentBlock('paragraph',
        '仅摘取形成材料时冻结的变化依据，不查询今天的数据重算。旧材料保留，是否采用本版由使用者决定；不同分类可能重叠，不相加为案件数。')]
    for key, label in [('recent_registered', '本期发现／案发并登记'), ('late_entry', '补录的历史情况'),
                       ('entry_time_uncertain', '登记但业务时间不确定'), ('corrections', '记录更正'),
                       ('withdrawals', '记录撤回或删除')]:
        value = origins.get(key)
        if not isinstance(value, dict):
            blocks.append(DocumentBlock('paragraph', f'{label}：此版未冻结分类依据，不能补推为零。'))
            continue
        blocks.append(DocumentBlock('table', value.get('label') or label, tuple(
            (heading, text(value.get(field))) for field, heading in
            [('count', '冻结数量（仅本分类）'), ('case_ids', '已存来源记录'), ('items', '已存修订依据')]
            if field in value)))
    blocks.append(DocumentBlock('heading', '同一周期再次出材料的变化'))
    if changes.get('state') == 'comparable':
        for item in changes.get('items', []):
            blocks.append(DocumentBlock('table', item.get('label') or '已存变化', (
                ('来源记录', text(item.get('case_ids'))), ('变化类别', text(item.get('kind'))))))
        blocks.append(DocumentBlock('paragraph', text(changes.get('boundary'))))
    else:
        blocks.append(DocumentBlock('paragraph', changes.get('reason') or '此版未保存可比较的上版变化依据，不能补算或认定无变化。'))
    for key, label in [('roads', '道路／入口资料变化'), ('tech_defense', '技防摘要变化')]:
        value = snapshot.get(key)
        blocks.append(DocumentBlock('table', label, (('形成材料时保存值', text(value)),)))
    blocks.append(DocumentBlock('paragraph', '生产、地图或道路资料变化只说明资料与关联条件变化，不改写案件发生数量；未保存的资料更新原因保持未知。'))
    return blocks


def options(kind):
    return [{'id': key, 'label': TEMPLATES[key]} for key in ('full', PER_KIND.get(kind)) if key]


def validate_template(kind, template):
    if template not in {item['id'] for item in options(kind)}:
        raise ValueError('material_template_not_applicable')


def _facility_sheet(result, document):
    body = result['body']
    blocks = [DocumentBlock('heading', '设施资料单'),
        DocumentBlock('paragraph', '概要格式：分类列出最多三条已有记录，不代表完整资料；完整明细及原文请切换同版本完整资料。'),
        DocumentBlock('table', '设施登记资料', tuple((LABELS.get(k, k), text(v)) for k, v in body['facility'].items())),
        DocumentBlock('table', '冻结时间条件', tuple((LABELS.get(k, k), text(v)) for k, v in body['filters'].items()))]
    temporal = body.get('temporal_context')
    if temporal:
        blocks.append(DocumentBlock('table', '历史条件可用性', tuple(
            (LABELS.get(key, key), text(temporal.get(key))) for key in
            ('state', 'coverage', 'query_interval', 'valid_at', 'known_at', 'knowledge_mode', 'late_supplement'))))
    sections = {'production': '生产与来源', 'record_links': '明确记录关联（不认定实际来源）',
        'nearby_cases': '空间邻近（不等于涉案）', 'candidate_links': '待核验候选关联',
        'events': '独立事件', 'results': '已有研判与报告', 'roads': '道路与可信入口',
        'tech_defense': '技防资料（缺资料不等于没有）', 'history_conditions': '历史条件对照'}
    for key, section in body['sections'].items():
        blocks.append(DocumentBlock('heading', sections.get(key, key)))
        state = section.get('state')
        blocks.append(DocumentBlock('paragraph', f'资料状态：{text(state)}'))
        if state in {'restricted', 'unavailable'}:
            # Never turn a restricted section into an existence/count hint.
            blocks.append(DocumentBlock('paragraph', '资料受限或不可读，不展示内容与数量。'))
            continue
        items = section.get('items', [])
        blocks.append(DocumentBlock('paragraph', f'匹配总数：{text(section.get("total"))}；本材料冻结 {len(items)} 条；本格式列出 {min(3, len(items))} 条。'))
        for item in items[:3]:
            blocks.append(DocumentBlock('table', item.get('label') or item.get('title') or '已记录条目',
                tuple((LABELS.get(field, field), text(item[field])) for field in
                    ('detail', 'value', 'case_id', 'event_id', 'source_id', 'source_revision',
                     'support', 'counter', 'gaps', 'evidence_refs') if field in item)))
        for field in ('gaps', 'boundary'):
            blocks.append(DocumentBlock('paragraph', f'{LABELS.get(field, field)}：{text(section.get(field))}'))
    blocks.extend((DocumentBlock('heading', '整份资料缺口'), DocumentBlock('paragraph', text(body.get('gaps'))),
        DocumentBlock('source', f'完整材料：facility/{result["id"]}；内容版本：{result["content_sha256"]}')))
    blocks.extend(block for block in document.blocks if block.kind == 'map')
    return blocks


def format_document(result, document, template='full', *, sections=None):
    validate_template(result['kind'], template)
    if sections is not None:
        return _section_projection(result, format_document(result, document, template), sections)
    if result['kind'] == 'situation':
        document = replace(document, blocks=tuple(list(document.blocks) + _period_change_blocks(result)))
    if template == 'full':
        return document
    # The reader crosses JSON while the exporter receives ORM datetimes.
    # Normalize before formatting so page and export are byte-for-byte alike.
    result = jsonable_encoder(result)
    if template == 'facility_sheet':
        blocks = _facility_sheet(result, document)
    elif template == 'case_summary':
        # Keep the fact/candidate/counterevidence/gap sections intact. The long
        # extraction transcript stays accessible in the full frozen document.
        blocks, skipping = [], False
        for block in document.blocks:
            if block.kind == 'heading' and block.text == '案情语义画像与原文引用':
                skipping = True
                blocks.append(DocumentBlock('paragraph', '本摘要省略逐项语义提取过程；原文位置、过程片段和全部提取限制保存在同版本完整资料，省略不表示没有限制。'))
            elif block.kind == 'map' or block.kind == 'heading' and block.text == '版本与适用边界':
                skipping = False
            if not skipping:
                blocks.append(block)
    else:
        # The existing period document already supplies the complete comparison,
        # assumptions and up-to-three suggestions. Reuse it without re-analysis.
        blocks = list(document.blocks)
    leading = [DocumentBlock('heading', TEMPLATES[template]), DocumentBlock('paragraph', BOUNDARY),
        DocumentBlock('source', f'材料：{result["kind"]}/{result["id"]}；形成时间：{result["created_at"]}；内容版本：{result["content_sha256"]}；格式版本：{SCHEMA}/{template}')]
    trailing = [DocumentBlock('paragraph', value) for value in result.get('boundary', [])]
    return replace(document, schema=f'{SCHEMA}/{template}', blocks=tuple(leading + blocks + trailing))


def present_result(result, template='full', *, expected_content_sha256=None, sections=None):
    if expected_content_sha256 and result['content_sha256'] != expected_content_sha256:
        raise ValueError('material_content_changed')
    output = deepcopy(result)
    saved = result['document']
    document = CaseResultDocument(saved['schema_version'], result['id'], result['content_sha256'],
        tuple(DocumentBlock(block['kind'], block['text'], tuple(tuple(row) for row in block.get('rows', [])))
              for block in saved['blocks']))
    document = format_document(result, document, template, sections=sections)
    output['document'] = {'schema_version': document.schema, 'blocks': jsonable_encoder([asdict(block) for block in document.blocks])}
    output['presentation'] = {'template': template, 'schema_version': SCHEMA, 'label': TEMPLATES[template],
        'options': options(result['kind']), 'boundary': BOUNDARY,
        'sections': validate_sections(sections), 'sections_customized': sections is not None,
        'section_options': [{'id': key, 'label': label} for key, label in SECTIONS.items()],
        'sections_boundary': SECTIONS_BOUNDARY}
    return output


def download_filename(result, format, template='full'):
    validate_template(result['kind'], template)
    if format not in {'docx', 'pdf'}:
        raise ValueError('invalid_document_format')
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', '_', result['title']).strip().rstrip('. ')[:90] or '未命名材料'
    created = result['created_at']
    created = created.isoformat() if isinstance(created, datetime) else str(created)
    date = re.match(r'^\d{4}-\d{2}-\d{2}', created)
    suffix = f'-{TEMPLATES[template]}' if template != 'full' else ''
    return f'{KIND_LABELS[result["kind"]]}-{title}-{date[0] if date else "日期待核"}-{result["content_sha256"][:8]}{suffix}.{format}'
