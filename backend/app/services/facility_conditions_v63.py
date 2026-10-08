"""Pure explanations of frozen facility evidence, never inferred endpoints."""
from copy import deepcopy

VERSION = "facility-conditions-6.3-1"
GAP_RANKING_VERSION = "facility-gap-impact-7.5-1"
HARD_ENTRY_REASONS = frozenset({"explicitly_closed", "traversal_permission_denied", "vehicle_limit_exceeded"})
BOUNDARY = "条件对照只解释已召回设施；硬排除仅针对本次已知通行条件，其他差异不等于排除实际来源。未知不按不符处理。"
ROAD_REASONS = {
    "restricted": "所有已核验入口均有明确通行限制，本次条件下不参与道路排序",
    "entrance_unknown": "入口、连接或适用通行条件尚不完整，不能形成道路比较",
    "permission_unknown": "通行许可资料不足",
    "no_path_found": "本次授权路网未取得路径；不证明现实中不存在道路",
    "network_missing": "缺少适用路网",
    "calculation_failed": "道路计算失败，不能据此排除设施",
    "not_calculated": "预算内尚未完成全部入口计算，不能确定该设施最优入口",
}
ENTRY_REASONS = {
    "explicitly_closed": "入口关闭或禁止通行", "traversal_permission_denied": "无通行授权",
    "vehicle_limit_exceeded": "已知车辆尺寸或总重超过入口限制",
    "vehicle_dimensions_missing": "缺少车辆高度或总重", "conditions_expired": "入口条件已过期",
    "conditions_not_yet_valid": "入口条件尚未生效", "conditions_unknown": "入口条件未知",
}
DEPENDENCIES = {
    "source": ["明确案发时间", "覆盖案发时段且已登记有效期的生产资料", "可用且无冲突的来源身份"],
    "road": ["入口明确对应设施", "入口与道路连通核验", "有效通行许可及车辆高度、总重"],
    "oil": ["案件明确油品", "案发时有效台账的油品记录"],
    "facility": ["案件明确设施类型", "案发时有效的设施用途资料"],
    "production": ["案件有效含水率测量及百分比单位", "台账含水率明确区间", "生产条件有效期覆盖案发时间"],
    "history": ["有原文出处的历史手法或地点条件", "历史油品和设施类型可核对"],
}
LABELS = {"source": "案发时生产资料", "road": "入口与道路", "oil": "油品", "facility": "设施用途",
          "production": "含水率", "history": "历史条件参考"}


def entrance_state(entries, *, source_verified):
    if not source_verified:
        return "entrance_unknown"
    if any(entry["eligible"] for entry in entries):
        return "not_calculated"
    if entries and all(entry.get("reason") in HARD_ENTRY_REASONS for entry in entries):
        return "restricted"
    return "entrance_unknown"


def _condition(key, state, reason, refs, *, value=None, dependencies=None):
    return {"key": key, "label": LABELS[key], "state": state, "reason": reason,
            "evidence_refs": sorted(set(refs)), "value": deepcopy(value),
            "dependencies": list(dependencies if dependencies is not None else DEPENDENCIES[key])
            if state == "unknown" else []}


def rank_priority_gaps(rows):
    """Rank observed unknowns, not hypothetical gain or uncomputed facilities."""
    groups = {}
    for row in rows:
        # A separate hard exclusion cannot be overturned by filling other fields.
        if row['eligibility'] == 'excluded':
            continue
        for condition in row['conditions']:
            if condition['state'] != 'unknown' or not condition['evidence_refs']:
                continue
            key = condition['key']
            blocks = key == 'road' and row['eligibility'] == 'unresolved'
            group = groups.setdefault(key, {'key': key, 'label': condition['label'], 'asset_ids': [],
                'condition_keys': [key], 'dependencies': [], 'impacts': [],
                'ranking_version': GAP_RANKING_VERSION})
            group['asset_ids'].append(row['asset_id'])
            group['dependencies'] = sorted(set(group['dependencies']) | set(condition['dependencies']))
            group['impacts'].append({'asset_id': row['asset_id'], 'name': row['name'],
                'eligibility': row['eligibility'], 'blocks_comparison': blocks,
                'reason': condition['reason'], 'evidence_refs': list(condition['evidence_refs'])})
    for group in groups.values():
        impacts = group['impacts']
        group['priority_basis'] = {
            'blocked_candidates': sum(item['blocks_comparison'] for item in impacts),
            'unresolved_candidates': sum(item['eligibility'] == 'unresolved' for item in impacts),
            'ranked_candidates': sum(item['eligibility'] == 'retained' for item in impacts),
            'affected_candidates': len(impacts),
        }
        counts = group['priority_basis']
        group['reason'] = (f"本轮已对照的 {counts['affected_candidates']} 个设施存在此项未知，"
                           f"其中 {counts['blocked_candidates']} 个因道路比较尚无可用结果而未进入排名。"
                           "补充或恢复计算后只能重新核对，不保证变为支持或排名上升；不含未计算设施及已有硬排除项。")
    return sorted(groups.values(), key=lambda item: (
        -item['priority_basis']['blocked_candidates'], -item['priority_basis']['affected_candidates'],
        -item['priority_basis']['unresolved_candidates'], item['key']))[:3]


def build_condition_comparison(pool, result):
    ranks = {item["asset_id"]: item for item in result["all_candidates"]}
    evidence = {item["asset_id"]: item for item in result["scoring_evidence"]}
    rows = []
    for asset in sorted(pool["assets"], key=lambda item: item["asset_id"]):
        identifier = asset["asset_id"]
        item, ranked = evidence[identifier], ranks.get(identifier)
        refs = [asset["evidence_ref"], *item["attribute_refs"]]
        road_refs = [asset["evidence_ref"], *[ref for ref in item["attribute_refs"] if ref.startswith("case_profile:")]]
        production_refs = [ref for ref in refs if not ref.startswith("case:")]
        context = asset["production_context"]
        historical = context.get("snapshot") or {}
        details = context.get("groups", {}).get("details", {})
        source_ready = (asset["source_verified"] and (
            details.get("coverage") == "full" and all(row["values"].get("verified") is True and row["values"].get("status") == "active"
                for row in details.get("segments", [])) if "groups" in context else
            context["state"] == "ready" and asset["source_verified"] and historical.get("verified") is True and historical.get("status") == "active"))
        source_reason = ("所引设施基础资料覆盖完整案发时间，且在本次资料截止前已登记；各字段组分别核对" if source_ready else
                         "；".join([*context.get("gaps", []), *([asset["source_gap"]] if asset.get("source_gap") else [])])
                         or "资料核验或历史适用时点不足")
        conditions = [_condition("source", "supported" if source_ready else "unknown", source_reason, production_refs,
                                 value={key: context.get(key) for key in ("valid_at", "version_id", "state")})]
        road = item["road_state"]
        road_state = "supported" if ranked else "hard_excluded" if road == "restricted" else "unknown"
        entry_refs = [f"internal_road_entrance:{entry['import_id']}:{entry['feature_id']}@review:{entry['review_id']}"
                      for entry in asset["entrances"]]
        detail = "；".join(sorted({ENTRY_REASONS[entry["reason"]] for entry in asset["entrances"]
                                  if entry.get("reason") in ENTRY_REASONS}))
        reason = (f"可信入口参考道路距离 {item['road_distance_m'] / 1000:.2f} 公里" if ranked
                  else ROAD_REASONS.get(road, "道路条件未知"))
        if detail:
            reason += "；" + detail
        road_dependencies = {"network_missing": ["适用路网资料"],
            "calculation_failed": ["道路计算服务恢复后重新计算（非案件补录）"],
            "not_calculated": ["完成本轮未计算的入口比较（非新增资料必填）"],
            "no_path_found": ["核对本次已知路网及入口连接资料，不以直线代替道路"]}.get(road)
        conditions.append(_condition("road", road_state, reason, [*road_refs, *entry_refs],
                                     dependencies=road_dependencies,
                                     value={"state": road, "distance_m": item["road_distance_m"],
                                            "entrance_reasons": sorted({e.get("reason") for e in asset["entrances"]})}))
        for key, match_field in (("oil", "oil_match"), ("facility", "facility_match"),
                                 ("production", "production_match"), ("history", "historical_match")):
            match = item[match_field]
            state = {"matched": "supported", "different": "different", "unknown": "unknown"}[match]
            comparison = asset.get(f"{key}_comparison", {})
            if key == "history":
                comparison = asset["history_comparison"]
            elif key == "production":
                comparison = asset["production_comparison"]
            messages = (comparison.get("support", []) if state == "supported" else
                        comparison.get("counter", []) if state == "different" else comparison.get("gaps", []))
            if key == "production" and state == "different":
                messages = [message for message in messages if not message.startswith("含水率条件相符")]
            reason = "；".join(messages) or f"{LABELS[key]}{'有来源支持的条件相符' if state == 'supported' else '存在明确记录差异' if state == 'different' else '资料不足，未按相符或不符处理'}"
            conditions.append(_condition(key, state, reason, refs if key == "history" else production_refs,
                value=comparison.get("comparison", asset.get(f"{key}_values"))))
        row = {"asset_id": identifier, "name": asset["name"],
               "eligibility": "retained" if ranked else "excluded" if road == "restricted" else "unresolved",
               "rank": ranked["rank"] if ranked else None, "score": ranked["score"] if ranked else None,
               "conditions": conditions, "source_context": {key: context.get(key)
                   for key in ("valid_at", "known_at", "version_id", "state", "query_interval", "time_precision",
                               "knowledge_mode", "coverage", "late_supplement", "groups", "boundary")}, "boundary": BOUNDARY}
        rows.append(row)
    gaps = rank_priority_gaps(rows)
    return {"schema_version": VERSION, "rows": rows, "priority_gaps": gaps, "boundary": BOUNDARY}


def compare_rankings(current, previous, *, baseline=None, context_changes=()):
    result = {"state": "no_baseline", "baseline": baseline, "changes": [],
              "context_changes": list(context_changes),
              "boundary": "仅比较两份真实冻结成果中的记录变化；名次变化不是准确率提升，也不能证明单一资料的因果作用。"}
    if previous is None:
        return result
    if previous.get("schema_version") != VERSION or current.get("schema_version") != VERSION:
        return {**result, "state": "not_comparable"}
    old = {row["asset_id"]: row for row in previous["rows"]}
    new = {row["asset_id"]: row for row in current["rows"]}
    if old.keys() != new.keys() and "recall_set" not in result["context_changes"]:
        result["context_changes"].append("recall_set")
    changes = []
    for identifier in sorted(old.keys() | new.keys()):
        before, after = old.get(identifier), new.get(identifier)
        prior = {condition["key"]: condition for condition in (before or {}).get("conditions", [])}
        updated = {condition["key"]: condition for condition in (after or {}).get("conditions", [])}
        delta = []
        for key in sorted(prior.keys() | updated.keys()):
            a, b = prior.get(key, {}), updated.get(key, {})
            if any(a.get(field) != b.get(field) for field in ("state", "value", "evidence_refs")):
                delta.append({"key": key, "previous_state": a.get("state"), "current_state": b.get("state"),
                              "evidence_refs": b.get("evidence_refs", []),
                              "previous_evidence_refs": a.get("evidence_refs", [])})
        old_rank, new_rank = (before or {}).get("rank"), (after or {}).get("rank")
        if not delta and old_rank == new_rank:
            continue
        reasons = []
        if before is None or after is None:
            reasons.append("本轮召回集合发生变化，新增或未再召回不等于现实来源已确认或排除")
        if delta:
            reasons.append("条件或引用版本变化：" + "、".join(LABELS.get(item["key"], item["key"]) for item in delta))
        if old_rank != new_rank:
            reasons.append("名次受全池相对次序影响，不能归因于某一条资料")
        if result["context_changes"]:
            reasons.append("案情、路网、算法或召回范围存在同步变化，不能归因于单一补充")
        changes.append({"asset_id": identifier, "name": (after or before)["name"],
                        "previous_rank": old_rank, "current_rank": new_rank,
                        "changed_conditions": delta, "reasons": reasons})
    return {**result, "state": "compared", "changes": changes}
