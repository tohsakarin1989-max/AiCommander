"""Compose authorized saved road evidence into the existing report, without routing."""
from dataclasses import replace
import json
import math

from app.services.case_road_artifact_service import read_road_artifact
from app.services.case_result_document import DocumentBlock
from app.services.road_polyline import decode_road_geometry  # Compatibility export for existing reports.


def load_document_road(db, result_id, source_hash, snapshot_id, artifact_id):
    artifact = read_road_artifact(db, artifact_id)
    content = artifact['content']
    if (content['result_id'], content['content_sha256'], content['map_snapshot_id']) != (
            result_id, source_hash, snapshot_id):
        raise ValueError('road_document_source_mismatch')
    if content['schema_version'] == 'case-road-route-4.2.0-1' and not snapshot_id:
        raise ValueError('road_document_map_required')
    return artifact


def _distance(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('invalid_road_document_distance')
    return f'{value / 1000:.2f} 公里'


def _detour_blocks(path, title):
    reference = path.get('detour_reference')
    if not reference:
        return []
    if reference.get('status') != 'available':
        return [DocumentBlock('paragraph', f'{title}：道路端点过近或测量精度不足，不显示绕行倍数。')]
    ratio = reference['ratio']
    if reference.get('basis') != 'route_geometry_endpoints' or type(ratio) not in (int, float) or not math.isfinite(ratio) or ratio < 1:
        raise ValueError('invalid_road_detour_reference')
    return [DocumentBlock('table', title, (
        ('道路端点直线距离', _distance(reference['straight_distance_m'])),
        ('沿路与直线距离比', f'{ratio:.2f} 倍'),
        ('多行距离', _distance(reference['additional_distance_m'])),
        ('适用边界', '基准为路径道路端点，不包含设施点位到道路的偏移，不代表行驶意图。'),
    ))]


def attach_road_document(document, artifact, *, map_spec=None):
    content = artifact['content']
    route = content['schema_version'] == 'case-road-route-4.2.0-1'
    facility = content['schema_version'] == 'case-facility-comparison-5.2-1'
    calculation = content['route'] if route else content['calculation'] if facility else content['matrix']
    blocks = [DocumentBlock('heading', '道路参考分析（历史留存）'),
        DocumentBlock('paragraph', '以下为已保存的计算结果，不在导出时重新计算；不代表当前仍可通行，也不是实际行驶轨迹或已确认事实。'),
        DocumentBlock('table', '道路成果与计算版本', (
            ('道路成果编号', artifact['id']), ('道路成果摘要', artifact['content_sha256']),
            ('保存时间', artifact['created_at'].isoformat()), ('计算条件时刻', calculation['analysis_at']),
            ('路网版本', calculation['network_id']), ('路网内容摘要', calculation['graph_sha256']),
            ('通行规则版本', str(calculation['policy_revision'])), ('地图快照', content['map_snapshot_id'] or '未记录'),
            ('车型', {'auto': '小客车', 'truck': '货车'}.get(calculation['vehicle']['kind'], '未记录')),
            ('车型依据', '明确参考假设' if calculation['vehicle']['source'] == 'explicit_reference_assumption' else '案件记录'),
            ('车型参数（存储值）', json.dumps(calculation['vehicle'], ensure_ascii=False, sort_keys=True)),
            ('计算引擎版本', calculation.get('engine_version') or '未记录'),
            ('计算结果结构版本', calculation.get('schema_version') or '未记录'),
        ))]
    if facility:
        result = content['result']
        coverage = result['coverage']
        blocks.append(DocumentBlock('paragraph', f"道路前置来源候选：召回 {coverage['recalled']} 个，完成比较 {coverage['compared']} 个。"))
        if not coverage['complete']:
            blocks.append(DocumentBlock('paragraph', '资料或计算不完整，不能据此认定全域最优候选。'))
        if not result['candidates']:
            blocks.append(DocumentBlock('paragraph', '尚无可展示候选，不等于没有关联设施。'))
        for item in result['candidates']:
            blocks.append(DocumentBlock('heading', f"候选 {item['rank']}：{item['name']}（编号 {item['asset_id']}）"))
            blocks.append(DocumentBlock('paragraph', f"可信入口参考道路距离：{_distance(item['road_distance_m'])}；规则支持度不是准确概率。"))
            blocks.extend(DocumentBlock('paragraph', '支持依据：' + value) for value in item['supporting_evidence'])
            blocks.extend(DocumentBlock('paragraph', '反向依据：' + value) for value in item['counter_evidence'])
            blocks.extend(DocumentBlock('paragraph', '资料缺口：' + value) for value in item['information_gaps'])
            blocks.extend(DocumentBlock('source', value) for value in item['evidence_refs'])
        labels = {'entrance_unknown': '入口或连接待核', 'restricted': '通行受限', 'permission_unknown': '许可资料不足',
                  'no_path_found': '未取得道路路径', 'calculation_failed': '计算失败', 'not_calculated': '尚未计算'}
        blocks.append(DocumentBlock('table', '未形成比较的设施（不按零分或低风险处理）', tuple(
            (str(item['asset_id']), labels.get(item['state'], '资料待核')) for item in result['unresolved'])))
        blocks.append(DocumentBlock('paragraph', '候选算法：' + result['algorithm_version']))
    elif route:
        if content.get('facility_comparison'):
            parent = content['facility_comparison']
            entry = content['target']['entrance']
            blocks.append(DocumentBlock('table', '道路前置候选与可信入口', (
                ('候选比较成果', parent['id']), ('比较成果摘要', parent['content_sha256']),
                ('入口来源批次', str(entry['import_id'])), ('入口来源编号', entry['feature_id']),
                ('入口核验记录', str(entry['review_id'])),
                ('端点边界', '本轮比较选定的可信入口，不确认设施内部连通或案发时实际通行。'),
            )))
            blocks.extend(DocumentBlock('source', ref) for ref in content['target']['evidence_refs'])
        blocks.append(DocumentBlock('table', '留存道路路径', (
            ('目标设施', content['target']['name']), ('目标设施编号', str(content['target']['asset_id'])),
            ('道路参考距离', _distance(calculation['distance_m'])),
        )))
        blocks.extend(_detour_blocks(calculation, '主路径绕行参考'))
        alternatives = calculation.get('alternatives', [])
        if not isinstance(alternatives, list) or len(alternatives) > 1:
            raise ValueError('invalid_road_alternatives')
        for index, alternative in enumerate(alternatives, 1):
            blocks.append(DocumentBlock('table', f'留存备选路径{index}', (
                ('道路参考距离', _distance(alternative['distance_m'])),
                ('来源依据', '同一道路成果编号与计算版本，非独立生成的案件事实'),
            )))
            blocks.extend(_detour_blocks(alternative, f'备选路径{index}绕行参考'))
        if calculation.get('alternatives_status') == 'no_distinct_alternative_returned':
            blocks.append(DocumentBlock('paragraph', '本轮未返回独立备选，不代表现实中只有主路径。'))
    else:
        rows = []
        for index, target in enumerate(content['targets']):
            cell = next((cell for cell in calculation['cells']
                         if cell['source_index'] == 0 and cell['target_index'] == index), None)
            rows.append((target['name'], _distance(cell['distance_m']) if cell and cell['status'] == 'calculated'
                         else '未取得参考路线，不等于现实中不可达'))
            blocks.append(DocumentBlock('source', target['evidence_ref']))
        blocks.append(DocumentBlock('table', '留存道路距离比较', tuple(rows)))
        blocks.extend(DocumentBlock('paragraph', gap) for gap in content['information_gaps'])
    blocks.append(DocumentBlock('paragraph', content['boundary']))
    if calculation.get('limitations'):
        blocks.append(DocumentBlock('paragraph', '计算限制（原始记录）：' + json.dumps(
            calculation['limitations'], ensure_ascii=False)))
    original = document.blocks
    if map_spec is not None:
        if (map_spec.get('road_artifact_id'), map_spec.get('road_artifact_sha256')) != (artifact['id'], artifact['content_sha256']):
            raise ValueError('facility_map_attachment_mismatch')
        # The source document remains immutable. This composite replaces only
        # its illustration, with an explicit old/new boundary and provenance.
        original = tuple(
            DocumentBlock('paragraph', '原空间附图见不带道路附件的原成果；本报告附图采用下方道路候选的冻结入口。')
            if block.kind == 'map' else
            DocumentBlock('heading', '原空间分析候选（历史参考，不与道路候选合并排名）')
            if block.kind == 'heading' and block.text == '待核验候选' else block
            for block in original)
        blocks.append(DocumentBlock('map', json.dumps(map_spec, ensure_ascii=False, allow_nan=False)))
    return replace(document, blocks=(*original, *blocks), road_artifact_id=artifact['id'],
                   road_artifact_sha256=artifact['content_sha256'])
