"""Chinese business sections from saved values; no interpretation or computation."""
from fastapi.encoders import jsonable_encoder
from app.services.case_result_document import CaseResultDocument, DocumentBlock

LABELS = {
    'id': '记录编号', 'name': '名称', 'title': '标题', 'label': '项目', 'detail': '记录说明',
    'summary': '摘要', 'content': '原文内容', 'status': '记录状态', 'state': '资料状态',
    'asset_type': '设施类别', 'external_id': '来源设施编号', 'operational_area_id': '所属辖区',
    'longitude': '经度', 'latitude': '纬度', 'verified': '核验标记',
    'case_id': '案件编号', 'case_number': '案件登记号', 'occurred_time': '案发时间',
    'event_id': '事件编号', 'event_type': '事件类别', 'location': '记录地点',
    'oil_type': '油品', 'owner_unit': '所属单位', 'production_unit': '生产单位',
    'production_output': '产量', 'production_status': '生产状态', 'water_cut_min': '含水率下限',
    'water_cut_max': '含水率上限', 'water_cut_unit': '含水率单位',
    'value': '记录值', 'unit': '单位', 'source': '来源', 'source_id': '来源编号',
    'evidence_refs': '证据引用', 'support': '支持依据', 'counter': '反向依据',
    'supporting_evidence': '支持证据', 'counter_evidence': '反向证据', 'gaps': '信息缺口',
    'information_gaps': '信息缺口', 'boundary': '适用边界', 'version': '版本',
    'profile_id': '画像编号', 'profile_version': '画像版本', 'source_version': '来源版本',
    'valid_from': '有效起始', 'valid_to': '有效截止', 'known_at': '入库截止', 'valid_at': '适用时刻',
    'query_interval': '完整业务时间区间', 'from': '区间起始', 'to': '区间截止',
    'knowledge_mode': '资料获知口径', 'coverage': '覆盖情况', 'late_supplement': '包含后来补录资料',
    'groups': '字段组', 'segments': '适用分段', 'end_inclusive': '包含终点', 'values': '分段资料',
    'start_date': '统计起始', 'end_date': '统计截止', 'distance_km': '直线距离（公里）',
    'distance_m': '道路距离（米）', 'map_snapshot_id': '地图快照', 'map_snapshots': '地图版本',
    'read_mode': '读取方式', 'schema_version': '内容结构版本', 'asset_updated_at': '设施更新时间',
    'section_versions': '分类内容校验', 'section_sources': '分类来源引用', 'view_version': '视图校验',
    'source_claim_ids': '台账声明编号', 'asset_version_ids': '设施历史版本编号',
    'map_manifest_hashes': '地图清单校验', 'content_sha256': '内容校验', 'input_sha256': '会议输入校验',
    'source_signature': '来源签名', 'source_data_version': '来源数据版本', 'created_at': '形成时间',
    'generated_at': '形成时间', 'algorithm_version': '算法版本', 'scope_policy_version': '范围规则版本',
    'period_type': '周期类别', 'period_start': '周期开始', 'period_end': '周期截止',
    'current': '本期', 'previous': '上一等长周期', 'case_count': '案件数', 'count': '数量',
    'change': '数量变化', 'case_ids': '来源案件编号', 'profile_case_ids': '来源画像案件编号',
    'rank': '展示顺序', 'target_area': '关注区域', 'time_window': '关注时段',
    'suggested_action': '工作参考', 'resource_assumption': '资源假设', 'expected_effect': '预期作用',
    'valid_until': '建议有效期', 'auto_execution_allowed': '是否允许自动执行',
    'confidence': '原记录支持度（不视为准确概率）', 'confidence_kind': '数值性质',
    'consensus_points': '讨论共识', 'disagreement_points': '不同意见',
    'model_contributions': '各模型讨论贡献', 'recommendations': '讨论建议', 'next_steps': '后续参考',
    'applicability': '适用条件', 'recorded_conditions': '冻结记录条件', 'recorded_fields': '原案登记内容',
    'facts_summary': '原始记录摘要', 'semantics': '冻结语义画像', 'process': '案件过程片段',
    'candidate_references': '候选参考（非事实）', 'frozen_result': '原案件成果',
    'action': '历史人工动作', 'note': '人工意见', 'reviewer_state': '历史判断人记载情况',
    'historical_reviews': '保留的人工记录', 'risk_level': '原历史分级（不重评分）',
    'report': '原案件报告', 'markdown': '原报告正文', 'sections': '原章节',
    'items': '条目', 'type': '条目类别', 'reused_experiences': '采纳的历史经验参考',
    'generation_mode': '形成方式', 'versions': '引用版本', 'ai_output': '原保存的模型输出',
}
STATES = {'ready': '可用', 'partial': '部分资料可用', 'empty': '未记录', 'missing': '缺失',
    'as_known': '当时已知', 'retrospective': '现在回看历史', 'full': '全区间覆盖',
    'restricted': '受限', 'unknown': '未知', 'stale': '已过期', 'candidate': '候选参考',
    'well': '井', 'draft': '草稿', 'confirmed': '已人工确认', 'archived': '已归档', 'published': '原记录已发布',
    'flagged': '已人工标记', 'rejected': '原记录未采纳', 'daily': '每日', 'weekly': '每周',
    'frozen_facility_material': '冻结设施材料', 'legacy_not_recorded': '旧数据未记载',
    'uncalibrated_rule_reference': '未经概率校准的规则参考'}


def text(value):
    if value is None:
        return '未提供'
    if isinstance(value, bool):
        return '是' if value else '否'
    if isinstance(value, dict):
        return '；'.join(f'{LABELS.get(key, key)}：{text(item)}' for key, item in value.items()) or '未记录'
    if isinstance(value, (list, tuple)):
        return '\n'.join(text(item) for item in value) or '未记录'
    return STATES.get(str(value), str(value))


def build(kind, identifier, digest, title, body, sources, boundary):
    body = jsonable_encoder(body)
    blocks = [DocumentBlock('heading', title), DocumentBlock('paragraph', boundary)]
    def paragraph(label, value):
        blocks.extend((DocumentBlock('heading', label), DocumentBlock('paragraph', text(value))))
    def fields(label, value):
        if not isinstance(value, dict):
            paragraph(label, value)
            return
        blocks.append(DocumentBlock('table', label, tuple((LABELS.get(key, key), text(item)) for key, item in value.items())))
    if kind == 'facility':
        fields('设施身份与位置', body['facility'])
        fields('本材料时间条件', body['filters'])
        if body.get('temporal_context'):
            fields('本材料设施历史条件与完整时间区间', body['temporal_context'])
        labels = {'production': '生产与台账资料', 'record_links': '明确记录关联（不等于来源认定）',
            'nearby_cases': '空间邻近案件（不等于涉案）', 'candidate_links': '候选关联与反向依据',
            'events': '独立事件', 'results': '已有研判成果', 'roads': '道路与可信入口',
            'tech_defense': '技防登记（缺资料不等于没有）', 'history_conditions': '历史条件对照'}
        for key, section in body['sections'].items():
            paragraph(labels.get(key, key), '资料状态：' + text(section['state']))
            if 'total' in section:
                paragraph('记录范围', f"匹配 {section['total']} 条，本材料保留 {len(section.get('items', []))} 条。")
            for index, item in enumerate(section.get('items', []), 1):
                fields(f"{index}. {item.get('label') or item.get('title') or '已记录条目'}", item)
            paragraph('分类信息缺口', section.get('gaps'))
            paragraph('分类适用边界', section.get('boundary'))
        paragraph('需要保留的未知', body['gaps'])
        fields('冻结版本及来源', body['versions'])
    elif kind == 'situation':
        paragraph('周期摘要', body['summary'])
        fields('统计口径', {key: body[key] for key in ('operational_area_id', 'period_type', 'period_start', 'period_end')})
        fields('冻结的等长周期对照', body.get('comparison_snapshot'))
        for item in body['recommendations']:
            fields(f"工作参考 {item['rank']}：{item['title']}", item)
        paragraph('证据引用', body['evidence_refs'])
        paragraph('未知与缺口', body['information_gaps'])
        fields('算法与形成时间', {key: body[key] for key in ('algorithm_version', 'scope_policy_version', 'generated_at')})
    elif kind == 'meeting':
        paragraph('讨论材料边界', body['boundary'])
        paragraph('输入版本状态', '冻结输入可追溯' if body['source_state'] == 'frozen' else '历史未保存输入版本，不补造事实来源')
        fields('原会议报告', body['content'])
        paragraph('讨论共识', body['consensus_points'])
        paragraph('不同意见', body['disagreement_points'])
        fields('模型讨论贡献', body['model_contributions'] or {})
    elif kind == 'experience':
        content = body['content']
        if body['asset_type'] == 'case_report':
            paragraph('历史案件报告边界', '以下保留原报告及原来源，不重新生成，不把报告表述自动认定为案件事实。')
            fields('原保存的案件报告', content)
        else:
            paragraph('经验摘要', content.get('summary'))
            fields('冻结原案记录', content.get('facts_summary', {}))
            paragraph('适用条件及差异边界', content.get('applicability'))
            paragraph('案件过程与语义依据', content.get('process') or content.get('semantics'))
            paragraph('候选参考，不作为新案件事实', content.get('candidate_references'))
            paragraph('信息缺口', content.get('information_gaps'))
            paragraph('确认及采纳边界', '只有经确认的经验可供采纳；历史相似不自动成为当前案件事实。')
            if not content.get('frozen_result'):
                fields('保留的历史经验正文', content)
        paragraph('原资料引用', body['evidence_refs'])
        fields('经验版本', {key: body[key] for key in ('version', 'source_signature', 'source_data_version')})
    elif kind == 'conclusion':
        paragraph('原历史表述', body['summary'])
        paragraph('历史记录状态', body['status'])
        fields('原保存依据（不重新解释为事实）', body['evidence'] or {})
        paragraph('原人工意见', body['historical_reviews'])
        paragraph('历史记录边界', body['boundary'])
    paragraph('可打开的冻结来源', sources)
    fields('本材料版本', {'id': str(identifier), 'content_sha256': digest})
    if sum(len(block.rows) for block in blocks) > 10000:
        raise ValueError('material_document_too_large')
    return CaseResultDocument('business-result-document-6.5-1', str(identifier), digest, tuple(blocks))
