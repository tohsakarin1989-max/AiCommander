"""Export an authorized frozen query, without another model call or fresh statistics."""
from app.services.case_result_document import CaseResultDocument, DocumentBlock
from app.services.case_result_export import render_docx
from app.services.case_result_pdf import _convert_generated_docx
from app.services.document_budget import document_budget
from app.services.intelligent_query_context import result_hash
from app.services.intelligent_query_tasks import read_query

SCHEMA = 'intelligent-query-document-4.3-1'
TOOLS = {'find_cases': '案件查找', 'find_places': '地点与设施', 'count_cases': '条件统计',
         'compare_periods': '时间段比较', 'summarize_results': '已有研判成果',
         'find_road_results': '历史道路成果', 'find_case_profiles': '案件语义画像'}
LABELS = {'assertions': '原文表述', 'batch_patterns': '本批表述分布（非全库规律）',
          'kind': '表述性质（stated明述、negated否定、uncertain不确定、inferred推断）',
          'reference': '原文引用', 'quote': '原句', 'category': '语义类别', 'value': '标准词项',
          'case_count': '本批去重案件数', 'count': '匹配案件数', 'current_count': '本期案件数', 'previous_count': '上一等长周期案件数',
          'change': '数量变化', 'items': '本批记录', 'total': '匹配总数', 'summary': '摘要',
          'title': '标题', 'claim': '候选推断', 'hypotheses': '候选（未确认）',
          'supporting_evidence': '支持证据', 'counter_evidence': '反向证据',
          'information_gaps': '信息缺口', 'evidence_refs': '证据引用', 'evidence_ref': '证据引用',
          'boundary': '适用边界', 'rule_support': '规则支持度（不是准确概率）',
          'case_number': '案件编号', 'case_type': '案件类型', 'location': '地点',
          'occurred_time': '案发时间', 'distance_m': '沿路距离（米）',
          'map_snapshot_id': '地图快照', 'network_id': '路网版本', 'policy_revision': '通行条件版本',
          'analysis_at': '计算时刻', 'queried_at': '查询时刻', 'tool_version': '工具版本',
          'source': '来源', 'filters': '查询条件', 'next_page': '下一批页码'}


def _rows(value, prefix='', depth=0):
    if depth > 16:
        raise ValueError('query_document_too_deep')
    if isinstance(value, dict):
        for key, item in value.items():
            label = LABELS.get(key, key)
            yield from _rows(item, f'{prefix} / {label}' if prefix else label, depth + 1)
    elif isinstance(value, list):
        if not value:
            yield (prefix, '未记录')
        for index, item in enumerate(value, 1):
            yield from _rows(item, f'{prefix} · {index}', depth + 1)
    else:
        yield (prefix, '未提供' if value is None else str(value))


def build_query_document(task):
    result = task.get('result') or {}
    if task['status'] not in {'completed', 'degraded'} or not result.get('cards'):
        raise ValueError('query_document_not_ready')
    blocks = [DocumentBlock('heading', '专题查询研判报告'),
              DocumentBlock('paragraph', task['query']),
              DocumentBlock('paragraph', '本报告为该次查询的历史快照。候选不等于正式事实；道路成果不代表实际行驶轨迹。未重新调用模型或更新统计。'),
              DocumentBlock('table', '运行版本', tuple(_rows({
                  'query_id': task['id'], 'status': task['status'],
                  'completed_at': task.get('completed_at'), 'error_code': result.get('error_code'),
                  'result_sha256': result_hash(result)}))),
              DocumentBlock('paragraph', '本报告保留地图与道路版本引用，不生成未核验的路线示意图。空结果、未完成计算和资料缺失不等于现实中不存在关联。')]
    if task.get('followup_context'):
        blocks.append(DocumentBlock('table', '追问来源与继承条件', tuple(_rows(task['followup_context']))))
    blocks.append(DocumentBlock('table', '本轮有效条件', tuple(_rows(result.get('query_conditions', {})))))
    for card in result['cards']:
        if card.get('tool') not in TOOLS:
            raise ValueError('query_document_unknown_tool')
        blocks.append(DocumentBlock('heading', TOOLS[card['tool']]))
        blocks.append(DocumentBlock('paragraph', f"结果状态：{card.get('state', '未知')}。列表仅代表本批返回内容，不替代全库统计。"))
        for label, value in [('查询成果', card.get('data', {})), ('证据与查询口径', card.get('evidence', {})),
                             ('信息缺口', card.get('information_gaps', []))]:
            blocks.append(DocumentBlock('table', label, tuple(_rows(value))))
        blocks.append(DocumentBlock('paragraph', card.get('boundary') or '仅供人工核验参考。'))
    blocks.append(DocumentBlock('table', '工具轨迹与条件变化', tuple(_rows(result.get('trace', [])))))
    if sum(len(block.rows) for block in blocks) > 10000:
        raise ValueError('query_document_too_large')
    return CaseResultDocument(SCHEMA, task['id'], result_hash(result), tuple(blocks))


@document_budget
def export_query_document(db, run_id, format):
    if format not in {'docx', 'pdf'}:
        raise ValueError('query_document_format')
    task = read_query(db, run_id)
    document = build_query_document(task)
    data = render_docx(document)
    if format == 'pdf':
        data = _convert_generated_docx(data)
    # Rendering can outlive a permission or source change. Never return stale authorization.
    db.expire_all()
    latest = read_query(db, run_id)
    if result_hash(latest.get('result')) != document.content_sha256 or latest['status'] != task['status']:
        raise PermissionError('query_document_changed')
    return document, data
