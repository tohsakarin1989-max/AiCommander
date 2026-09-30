"""Project the same frozen process/condition evidence into existing documents."""


def process_blocks(process):
    from app.services.case_result_document import DocumentBlock

    kinds = {"stated": "原文陈述", "negated": "原文否定", "uncertain": "不确定", "inferred": "推断"}
    units = {"tonne": "吨", "liter": "升", "kg": "千克", "m3": "立方米", "unknown": "单位未知"}
    precisions = {"hour": "小时精度", "minute": "分钟精度"}
    dimensions = {"action": "动作", "time": "时间", "object": "对象", "place_role": "地点角色", "measurement": "计量依据"}
    blocks = [DocumentBlock("heading", "案件过程依据"),
              DocumentBlock("paragraph", process["boundary"]),
              DocumentBlock("paragraph", f"过程版本：{process['version']}；来源版本：{process['source_revision_id']}。")]

    def reference(ref):
        import json
        path = " / ".join(str(part) for part in ref["snapshot_path"])
        text = (f"字符 {ref['start'] + 1} 至 {ref['end']}：{ref['quote']}" if ref["kind"] == "text"
                else json.dumps(ref["value"], ensure_ascii=False, sort_keys=True))
        return DocumentBlock("source", f"来源版本 {ref['source_revision_id']} · {path} · {text}")

    for index, event in enumerate(process["events"], 1):
        actions = "；".join(f"{item['value']}（{kinds.get(item['kind'], '待核')}）" for item in event["actions"])
        blocks.append(DocumentBlock("heading", f"已交代环节 {index}：{actions or '动作未明确'}"))
        blocks.append(DocumentBlock("paragraph", "规则整理候选，句内共现不证明主客体关系。"))
        blocks.append(reference(event["reference"]))
        if event["objects"]:
            objects = "、".join(f"{item['value']}（{kinds.get(item['kind'], '待核')}）" for item in event["objects"])
            blocks.append(DocumentBlock("paragraph", f"同句涉及：{objects}；同句出现不证明主客体关系。"))
        for interval in event["time_intervals"]:
            start_precision = precisions.get(interval["start_precision"], "精度未明确")
            end_precision = precisions.get(interval["end_precision"], "精度未明确")
            blocks.append(DocumentBlock("paragraph", f"原文时间：{interval['start']}（{start_precision}）至 {interval['end']}（{end_precision}，{interval['timezone'] or '时区未注明'}）；不自动作为已确认发生时间。"))
            blocks.append(reference(interval["reference"]))
        for location in event["locations"]:
            role = {"source": "原文来源", "destination": "原文去向"}.get(location["role"], "角色未知")
            blocks.append(DocumentBlock("paragraph", f"{role}：{location['value']}（{kinds.get(location['kind'], '待核')}）"))
            blocks.append(reference(location["reference"]))
        for measurement in event["measurements"]:
            blocks.append(DocumentBlock("paragraph", f"原文计量：{measurement['oil_type']} {measurement['value']} {units[measurement['unit']]}（{kinds.get(measurement['kind'], '待核')}）；阶段未知，未合并其他计量。"))
            blocks.append(reference(measurement["reference"]))
        if event["missing_dimensions"]:
            blocks.append(DocumentBlock("paragraph", "本环节未明确的维度：" + "、".join(dimensions.get(key, key) for key in event["missing_dimensions"]) + "；不作为新增必填要求。"))
    for relation in process["relations"]:
        blocks.append(DocumentBlock("paragraph", f"原文明示先后表述（{kinds.get(relation['kind'], '待核')}），未经确认，不等于实际顺序或因果。"))
        blocks.append(reference(relation["reference"]))
    for conflict in process["conflicts"]:
        blocks.append(DocumentBlock("paragraph", f"不同表述待核：{conflict['value']}；核对是否相同时段和对象，不自动选择结论。"))
        blocks.extend(reference(ref) for ref in conflict["references"])
    for category in ("locations", "measurements"):
        for item in process["structured_context"][category]:
            blocks.append(DocumentBlock("paragraph", "案件背景记录，未自动绑定到某个环节，不混算单位或计量阶段。"))
            blocks.append(reference(item["reference"]))
    if process["coverage"]["state"] == "partial":
        blocks.append(DocumentBlock("paragraph", "当前过程提取不完整，未覆盖内容保留未知。"))
    return blocks


def condition_blocks(comparison, changes=None):
    from app.services.case_result_document import DocumentBlock

    states = {"hard_excluded": "当前计算条件排除", "different": "明确不符", "unknown": "资料未知", "supported": "条件支持"}
    blocks = [DocumentBlock("heading", "设施全池条件对照"), DocumentBlock("paragraph", comparison["boundary"])]
    for row in comparison["rows"]:
        blocks.append(DocumentBlock("heading", f"{row['name']}（稳定编号 {row['asset_id']}）"))
        blocks.append(DocumentBlock("paragraph", row["boundary"]))
        for condition in row["conditions"]:
            blocks.append(DocumentBlock("paragraph", f"{condition['label']} · {states[condition['state']]}：{condition['reason']}"))
            blocks.extend(DocumentBlock("source", ref) for ref in condition["evidence_refs"])
            if condition["dependencies"]:
                blocks.append(DocumentBlock("paragraph", "依赖资料：" + "、".join(condition["dependencies"])))
        source = row["source_context"]
        blocks.append(DocumentBlock("paragraph", f"生产资料适用时刻：{source.get('valid_at') or '未知'}；资料截止：{source['known_at']}；来源版本：{source.get('version_id') or '未取得'}。"))
    for gap in comparison["priority_gaps"]:
        blocks.append(DocumentBlock("paragraph", f"补充依赖：{gap['label']} · {gap['reason']}；需补：{'、'.join(gap['dependencies'])}。不是新增待办或命中概率承诺。"))
    if changes:
        blocks.append(DocumentBlock("heading", "与前一可比成果的变化"))
        blocks.append(DocumentBlock("paragraph", changes["boundary"]))
        if changes.get("baseline"):
            blocks.append(DocumentBlock("source", f"前版成果：{changes['baseline']['artifact_id']}；摘要：{changes['baseline']['content_sha256']}"))
        if changes["state"] != "compared":
            blocks.append(DocumentBlock("paragraph", "没有满足条件的可比前版，不编造名次变化。"))
        for change in changes["changes"]:
            blocks.append(DocumentBlock("paragraph", f"{change['name']}：前版名次 {change['previous_rank']} → 本版名次 {change['current_rank']}；空值表示未排名。"))
            blocks.extend(DocumentBlock("paragraph", reason) for reason in change["reasons"])
            for condition in change["changed_conditions"]:
                blocks.append(DocumentBlock("paragraph", f"{condition['key']}：{condition['previous_state']} → {condition['current_state']}"))
                blocks.extend(DocumentBlock("source", ref) for ref in condition["evidence_refs"])
                blocks.extend(DocumentBlock("source", "前版：" + ref) for ref in condition.get("previous_evidence_refs", []))
        if changes["context_changes"]:
            blocks.append(DocumentBlock("paragraph", "同时变化的条件：" + "、".join(changes["context_changes"])))
    return blocks
