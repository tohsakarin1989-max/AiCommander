"""Evidence-bound answer projection. No model-generated facts or references."""
from collections import Counter
import json


BOUNDARY = '答案仅组织本轮工具已返回的依据；候选、历史参考和情景假设不等于正式事实或执行指令。'


def compose_answer(cards):
    findings, gaps = [], []
    for index, card in enumerate(cards):
        data = card.get('data') or {}
        tool = card.get('tool')
        refs = data.get('evidence_refs') or [f'query_card:{index}']

        def add(text, evidence=None):
            findings.append({'text': text, 'card_index': index, 'evidence_refs': evidence or refs})

        gaps.extend(card.get('information_gaps') or [])
        if tool == 'count_cases':
            add(f"本轮授权条件下共有 {data['count']} 起案件。")
        elif tool == 'compare_periods':
            add(f"本期 {data['current_count']} 起，上一等长周期 {data['previous_count']} 起，数量变化 {data['change']:+d} 起。")
        elif tool in {'find_cases', 'find_places', 'find_case_profiles'}:
            add(f"符合本轮筛选的记录共 {data.get('total', 0)} 项，本批展示 {len(data.get('items', []))} 项；列表不是全部证据。")
        elif tool == 'read_case_process':
            process = data.get('process')
            if process:
                events = process['events']
                kinds = Counter(item['statement_kind'] for item in events)
                labels = {'stated': '明述', 'negated': '否定', 'uncertain': '不确定', 'inferred': '推断', 'mixed': '混合表述'}
                detail = '、'.join(f"{labels.get(key, key)} {value} 项" for key, value in sorted(kinds.items()))
                add(f"该版案件过程包含 {len(events)} 个原文片段（{detail or '暂无可用表述'}）；共现不等于已证实关系。")
                for item in events[:3]:
                    ref = item['reference']
                    add(f"原文片段：{ref['quote']}（{labels.get(item['statement_kind'], '待核对')}）。",
                        [*refs, f"process_event:{item['id']}"])
        elif tool == 'explain_case_result' and data.get('result'):
            result = data['result']; content = result['content']
            candidates = content.get('candidates', [])
            add(f"读取冻结成果 {result['id']}，候选 {len(candidates)} 项；"
                + ('这是指定历史版本，不代表当前条件。' if data['result_basis'] == 'specified_historical_result' else '当前就绪情况以工具状态为准。'))
            comparison = content.get('road_condition_comparison') or {}
            for row in comparison.get('rows', [])[:3]:
                counts = Counter(item.get('state') for item in row.get('conditions', []))
                add(f"设施 ID {row.get('asset_id')}：支持 {counts['supported']}、未知 {counts['unknown']}、排除 {counts['hard_excluded']}、不符 {counts['different']} 项；不是发案概率。")
        elif tool == 'read_facility_dossier':
            dossier = data['dossier']; sections = dossier['sections']
            add(f"已读取设施 {dossier['facility'].get('name', data['asset_id'])} 的资料档案；明确关联、邻近和候选分开呈现。")
            for key, label in [('record_links', '明确记录关联'), ('nearby_cases', '空间邻近'), ('candidate_links', '候选关联')]:
                section = sections.get(key, {})
                if section.get('state') == 'restricted':
                    gaps.append(f'{label}资料受限，不显示数量或摘要。')
                else:
                    add(f"{label}：本批 {len(section.get('items', []))} 项；空间邻近与候选不能当作涉案事实。")
            gaps.extend(dossier.get('gaps', []))
        elif tool == 'read_facility_at':
            historical = data['historical']
            add(f"按有效时间 {historical['valid_at']}、已知时间 {historical['known_at']} 核对设施资料："
                + (f"取得版本 {historical['version_id']}。" if historical['state'] == 'ready' else '未取得可用一致版本，保留未知。'))
        elif tool == 'compare_coverage_scenario':
            value = data['comparison']
            frozen = value['input_snapshot']
            add(f"情景时点 {frozen['as_of']}；假设停用设备 ID：{frozen['disabled_resource_ids']}；"
                f"假设移动：{frozen['movements']}。这些参数不是已发生事实。")
            add(f"登记井点名义覆盖：基准 {value['baseline']['covered_count']} 处，假设方案 {value['scenario']['covered_count']} 处，变化 {value['covered_count_change']:+d} 处。")
            add(f"假设方案资料未知的井点 {value['scenario']['unknown_count']} 处；未改变设备和设施记录，未创建执行任务。")
        elif tool == 'find_history':
            add(f"本轮返回 {len(data.get('items', []))} 项历史参考；检索支持度不是事实认定或总体统计。")
        elif tool == 'aggregate_case_profiles':
            coverage = data.get('coverage', {})
            add('已完成授权集合的条件统计。' if coverage.get('complete') else '当前仅取得部分统计，尚不能回答全库总体。')
        elif tool == 'read_business_result':
            value = data['business_result']
            add(f"已读取 {value['title']} 的冻结成果，类型 {value['kind']}；不重新计算或混同各类成果含义。")
        elif tool == 'find_business_results':
            add(f"本批找到 {len(data.get('catalog', {}).get('items', []))} 项可访问成果。")
        else:
            add(f"已读取 {len(data.get('items', []))} 项业务结果；具体依据和版本见对应工具记录。")
    gap_text = [gap if isinstance(gap, str) else (gap.get('message') or gap.get('reason') or
                gap.get('description') or json.dumps(gap, ensure_ascii=False)) for gap in gaps]
    return {'schema_version': 'query-answer-6.4-1',
            'summary': '已按本轮授权条件整理可核对的业务依据。' if findings else '当前没有足够依据回答，请查看信息缺口。',
            'findings': findings, 'information_gaps': list(dict.fromkeys(gap_text)), 'boundary': BOUNDARY}
