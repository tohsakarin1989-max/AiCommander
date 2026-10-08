"""Export an authorized frozen query, without another model call or fresh statistics."""
from app.services.case_result_document import CaseResultDocument, DocumentBlock
from app.services.case_result_export import render_docx
from app.services.case_result_pdf import _convert_generated_docx
from app.services.document_budget import document_budget
from app.services.intelligent_query_context import result_hash
from app.services.intelligent_query_tasks import read_query

SCHEMA = 'intelligent-query-document-4.3-1'
TOOLS = {'find_cases': '案件查找', 'find_places': '地点与设施', 'count_cases': '条件统计',
         'business_attention': '区域与设施关注依据', 'business_recent_changes': '业务时间与变化来源',
         'compare_periods': '时间段比较', 'summarize_results': '已有研判成果',
         'find_road_results': '历史道路成果', 'find_case_profiles': '案件语义画像',
         'find_history': '历史案件与经验参考', 'aggregate_case_profiles': '全库画像条件统计',
         'read_case_process': '案件过程与原文证据', 'explain_case_result': '已有成果解释',
         'read_facility_dossier': '设施综合档案', 'read_facility_at': '历史有效资料',
         'compare_coverage_scenario': '登记资源名义覆盖情景',
         'find_business_results': '统一成果目录', 'read_business_result': '统一成果阅读'}
LABELS = {'statistics': '已遍历集合统计', 'matched': '满足全部条件', 'unmatched': '不同或相反表述',
          'time_precision_counts': '时间精度分类数（精确、区间、未知）',
          'current_time_precision_counts': '本期时间精度分类数（精确、区间、未知）',
          'previous_time_precision_counts': '前期时间精度分类数（精确、区间、未知）',
          'occurred_from': '原始区间起点', 'occurred_to': '原始区间终点',
          'time_precision': '原始时间精度', 'time_expression': '原始时间表述', 'time_timezone': '原始时区',
          'fragment': '实际命中片段', 'source_revision_id': '原始来源版本', 'process_event_id': '过程片段编号',
          'indexed_cases': '已建立片段索引的案件数', 'missing_index_cases': '尚未就绪索引的案件数',
          'indexed_fragments': '索引片段数', 'recalled_fragments': '本轮召回片段数',
          'validated_fragments': '已复核片段数', 'invalidated_fragments': '失效片段数',
          'recall_limit': '各分支召回上限', 'recall_truncated': '是否达到召回上限',
          'structural_rank': '结构条件名次', 'lexical_rank': '词项名次', 'semantic_rank': '本地语义名次',
          'unknown': '条件资料不足', 'denominator': '统计分母', 'missingness': '类别表述缺失比例',
          'missing_count': '无该类表述的画像数', 'ratio': '比例', 'patterns': '匹配案组条件分布',
          'condition_statistics': '各条件统计', 'counterexamples': '不同或相反表述案例',
          'unknown_examples': '资料不足案例', 'profile_states': '画像可用状态',
          'coverage': '实际检索覆盖', 'authorized_cases': '候选范围案件数', 'scanned_cases': '已检查案件数',
          'matched_sources': '匹配资料来源数（非案件总数）', 'complete': '是否完成全部候选范围',
          'shared_conditions': '相似条件', 'different_conditions': '不同表述',
          'unmatched_query_conditions': '尚未匹配条件', 'snippet': '原文摘录',
          'score': '检索支持度（不是准确概率）', 'versions': '来源版本',
          'assertions': '原文表述', 'batch_patterns': '本批表述分布（非全库规律）',
          'kind': '表述性质（stated明述、negated否定、uncertain不确定、inferred推断）',
          'reference': '原文引用', 'quote': '原句', 'category': '语义类别', 'value': '标准词项',
          'case_count': '该条件去重案件数（统计范围见所属结果）', 'count': '匹配案件数', 'current_count': '本期案件数', 'previous_count': '上一等长周期案件数',
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
    if result.get('answer'):
        answer = result['answer']
        blocks.extend([DocumentBlock('heading', '证据化回答'), DocumentBlock('paragraph', answer['summary']),
                       DocumentBlock('paragraph', answer['boundary'])])
        for finding in answer['findings']:
            blocks.append(DocumentBlock('paragraph', finding['text']))
            blocks.append(DocumentBlock('paragraph', '依据：' + '、'.join(finding['evidence_refs'])))
        blocks.append(DocumentBlock('table', '信息缺口', tuple(_rows(answer['information_gaps']))))
        if answer.get('schema_version') == 'business-answer-8.4-1':
            labels = {'answered': '已回答', 'partial': '部分回答', 'insufficient_data': '资料不足',
                      'service_unavailable': '依赖服务不可用'}
            blocks.extend([
                DocumentBlock('paragraph', '回答完整度：' + labels.get(answer.get('completeness'), '未声明')),
                DocumentBlock('paragraph', answer.get('direct_answer', '')),
                DocumentBlock('table', '支持依据', tuple(_rows(answer.get('evidence', [])))),
                DocumentBlock('table', '差异或反向情况', tuple(_rows(answer.get('differences', [])))),
                DocumentBlock('table', '尚不能回答的部分', tuple(_rows(answer.get('unanswered', [])))),
                DocumentBlock('table', '时间、范围与版本', tuple(_rows(answer.get('time_scope_versions', {})))),
            ])
    for card in result['cards']:
        if card.get('tool') not in TOOLS:
            raise ValueError('query_document_unknown_tool')
        blocks.append(DocumentBlock('heading', TOOLS[card['tool']]))
        blocks.append(DocumentBlock('paragraph', f"结果状态：{card.get('state', '未知')}。列表仅代表本批返回内容，不替代全库统计。"))
        if card['tool'] == 'aggregate_case_profiles':
            blocks.append(DocumentBlock('paragraph', '总体分母与扫描完成度见 coverage；案组计数与分页代表案例分开。未知不当作否定。'))
        if card['tool'] == 'find_history' and card.get('data', {}).get('retrieval_mode') == 'fragment_index':
            blocks.append(DocumentBlock('paragraph', '片段检索仅复核本轮召回候选，不逐案扫描原文；索引缺失或达到预算上限时不是全库无匹配。'))
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
    if (task.get('result', {}).get('answer') or {}).get('schema_version') == 'business-answer-8.4-1':
        # Unified reader/Word/PDF share the frozen map and answer. The catalogue
        # calls build_query_document (not this exporter), so this is not recursion.
        from app.services.result_document import export_result
        return export_result(db, 'query', run_id, format)
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
