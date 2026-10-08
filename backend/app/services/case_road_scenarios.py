"""Controlled, fixed-input comparisons; never edits roads or case facts."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime

from app.models.jurisdiction import JurisdictionAsset
from app.models.road_network import RoadNetworkVersion
from app.services.case_analysis_applicability import allows
from app.services.case_result_service import CaseResultService
from app.services.case_road_artifact_service import read_road_artifact
from app.services.facility_analysis_versions import current_versions
from app.services.facility_candidate_pool import (
    FACILITY_TERMS, _production_context, _production_refs, _production_signature, digest,
    require_current_pool_source, verified_entrances,
)
from app.services.facility_conditions_v63 import build_condition_comparison
from app.services.facility_history_conditions import facility_history_match
from app.services.facility_production_conditions import production_comparison
from app.services.facility_temporal_conditions import _load, group_match, validate_temporal_access
from app.services.road_access_policy import VehicleAssumption
from app.services.road_network_service import resolve_network
from app.services.scorers.facility_roads_v63 import FacilityEvidence, rank_facilities

VERSION = "case-road-scenarios-8.3-1"
BOUNDARY = ("同一冻结设施池、资料截止和评分规则下的条件参考；保留现实硬限制和当前权限。"
            "多个情景均保留依据也不等于已确认来源、实际轨迹或准确概率；不声称全域最优。")


def _at(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("scenario_timezone_required")
    return stamp


def read_baseline(db, artifact_id, expected_hash=None, *, current=False):
    saved = read_road_artifact(db, artifact_id)
    content = saved["content"]
    if (content.get("schema_version") != "case-facility-comparison-5.2-1"
            or expected_hash is not None and saved["content_sha256"] != expected_hash):
        raise ValueError("scenario_baseline_changed")
    source = CaseResultService.read(db, content["result_id"])
    if not allows(source["content"], "road_analysis"):
        raise ValueError("road_analysis_not_applicable")
    if current:
        require_current_pool_source(db, content["pool"])
        if content.get("algorithm_versions") != current_versions():
            raise ValueError("scenario_algorithm_unavailable")
    result = content["result"]
    if not result.get("road_completion", {}).get("complete") or not isinstance(result.get("scoring_evidence"), list):
        raise ValueError("scenario_baseline_incomplete")
    return saved, source


def _family(network):
    """Only a different vehicle over the same governed source/policy is comparable."""
    manifest = network.source_manifest or {}
    revision = manifest.get("source_revision")
    if not isinstance(revision, dict):
        return None
    return {"group": network.group_id, "policy": network.policy_revision,
            "public_bundle": network.public_bundle_id, "source_revision": revision,
            "engine": network.engine_version, "builder": network.builder_version}


def _catalog(db, saved):
    content, options = saved["content"], []
    pool, calculation = content["pool"], content["calculation"]
    cutoff, at = _at(pool["production_known_at"]), _at(calculation["analysis_at"])
    for asset in pool["assets"]:
        for entry in asset["entrances"]:
            if entry["eligible"]:
                options.append({"kind": "extra_entrance_exclusion", "label": f"不使用 {asset['name']} 的入口 {entry['feature_id']} 作为目标连接",
                    "parameters": {"asset_id": asset["asset_id"], "source_id": entry["source_id"],
                                   "feature_id": entry["feature_id"], "review_id": entry["review_id"],
                                   "exclusion_scope": "target_connection_only"},
                    "evidence_refs": [f"internal_road_entrance:{entry['import_id']}:{entry['feature_id']}@review:{entry['review_id']}"]})
    periods = {}
    for item in pool["assets"]:
        asset = db.query(JurisdictionAsset).filter_by(id=item["asset_id"]).first()
        if asset is None:
            raise PermissionError("scenario_source_unavailable")
        groups, restricted = _load(db, asset, cutoff)
        if groups is None:
            continue
        for key, rows in groups.items():
            if key == "geometry" or key in restricted:
                continue
            for row in rows:
                start, end = row["start"], row["end"]
                if start is None or end is None or start >= end or row["state"] != "set":
                    continue
                period = (start.isoformat(), end.isoformat())
                periods.setdefault(period, set()).update(row["refs"])
    for (start, end), refs in sorted(periods.items(), reverse=True)[:20]:
        options.append({"kind": "production_period", "label": f"生产资料有效期 {start[:10]} 至 {end[:10]}",
            "parameters": {"valid_from": start, "valid_to": end}, "evidence_refs": sorted(refs)})
    base = db.query(RoadNetworkVersion).filter_by(id=calculation["network_id"]).one()
    from app.services.road_scenario_networks import eligible_exclusion_options
    for registered in eligible_exclusion_options(db, base.id, analysis_at=at,
            vehicle=VehicleAssumption.model_validate(calculation["vehicle"])):
        options.append({"kind": "extra_road_exclusion", "label": registered["label"],
            "parameters": {key: value for key, value in registered.items() if key not in {"label", "evidence_refs"}},
            "source_retained": bool((base.source_manifest or {}).get("retained_source")),
            "evidence_refs": registered["evidence_refs"]})
    family = _family(base)
    if family is not None:
        graphs = db.query(RoadNetworkVersion).filter_by(group_id=base.group_id, policy_revision=base.policy_revision,
            status="ready", public_bundle_id=base.public_bundle_id).order_by(RoadNetworkVersion.id).all()
        seen = set()
        original = VehicleAssumption.model_validate(calculation["vehicle"]).model_dump(exclude={"source"})
        for graph in graphs:
            if _family(graph) != family:
                continue
            try:
                vehicle = VehicleAssumption.model_validate((graph.source_manifest or {}).get("vehicle"))
                if vehicle.kind == "truck" and (vehicle.height_m is None or vehicle.weight_t is None):
                    continue
                binding = resolve_network(db, graph.id, analysis_at=at, vehicle=vehicle)
            except (PermissionError, ValueError):
                continue
            fields = vehicle.model_dump(exclude={"source"})
            key = digest(fields)
            if fields == original or key in seen:
                continue
            seen.add(key)
            options.append({"kind": "reference_vehicle", "label": ("已登记小客车参考" if vehicle.kind == "auto" else
                f"已登记货车参考：高 {vehicle.height_m:g} 米、总重 {vehicle.weight_t:g} 吨"),
                "parameters": {"network_id": graph.id, "graph_sha256": binding.graph_sha256,
                               "vehicle": {**vehicle.model_dump(), "source": "explicit_reference_assumption"}},
                "evidence_refs": [f"road_network:{graph.id}@graph:{binding.graph_sha256}"]})
    for option in options:
        option["id"] = digest({"artifact": saved["content_sha256"], **option})
    return options


def scenario_options(db, artifact_id):
    saved, _ = read_baseline(db, artifact_id, current=True)
    options = _catalog(db, saved)
    return {"schema_version": VERSION, "artifact_id": saved["id"], "artifact_sha256": saved["content_sha256"],
        "options": options, "max_scenarios": 3, "baseline_included": True,
        "capabilities": {kind: {"state": "available" if any(row["kind"] == kind for row in options) else "information_missing"}
            for kind in ("production_period", "reference_vehicle", "extra_entrance_exclusion")},
        "road_exclusions": {"state": "available" if any(row["kind"] == "extra_road_exclusion" and row["source_retained"] for row in options) else "not_ready",
            "reason": "已登记道路可在后台准备严格子图；缺少所绑定的原始源包时保留未就绪，不使用软避让代替。"},
        "boundary": BOUNDARY}


def _production_variant(db, content, option):
    pool = deepcopy(content["pool"])
    source = CaseResultService.read(db, content["result_id"])["content"]
    standard, facts = source["facts_summary"]["recorded_fields"], source["related_conditions"]
    known = _at(pool["production_known_at"])
    parameters = option["parameters"]
    rows = {item["asset_id"]: item for item in deepcopy(content["result"]["scoring_evidence"])}
    for asset in pool["assets"]:
        temporal = _production_context(db, asset["asset_id"], known_at=known,
            valid_from=_at(parameters["valid_from"]), valid_to=_at(parameters["valid_to"]), end_inclusive=False)
        details = temporal.get("groups", {}).get("details", {})
        values = [row["values"] for row in details.get("segments", []) if row["state"] == "ready"]
        verified = asset["source_verified"] and details.get("coverage") == "full" and bool(values) and all(
            value.get("verified") is True and value.get("status") == "active" for value in values)
        oil = group_match(temporal, "details", lambda value: None if not standard.get("oil_type") or not value.get("oil_type")
                          else standard["oil_type"] == value["oil_type"]) if verified else "unknown"
        facility_type = values[0].get("asset_type") if values and all(value.get("asset_type") == values[0].get("asset_type") for value in values) else None
        expected = FACILITY_TERMS.get(facility_type, set())
        facility = ("unknown" if not verified or not expected or not standard.get("facility_type") else
                    "matched" if standard["facility_type"] in expected else "different")
        oil_type = values[0].get("oil_type") if values and all(value.get("oil_type") == values[0].get("oil_type") for value in values) else None
        production = production_comparison(attributes={}, verified=asset["source_verified"], case_fields=standard,
                                           case_facts=facts, temporal_context=temporal)
        historical = facility_history_match(pool["history"], asset_type=facility_type, oil_type=oil_type, verified=verified)
        asset.update(production_context=temporal, production_context_sha256=_production_signature(temporal),
            production_comparison=production, history_comparison=historical,
            oil_match=oil, facility_match=facility, oil_values={"case": standard.get("oil_type"), "facility": oil_type},
            facility_values={"case": standard.get("facility_type"), "facility": facility_type})
        row = rows[asset["asset_id"]]
        row.update(oil_match=oil, facility_match=facility, production_match=production["state"], historical_match=historical["state"],
            attribute_refs=[f"case_profile:{pool['versions']['case_profile_id']}", asset["evidence_ref"],
                            *_production_refs(temporal), *(f"case:{identifier}" for identifier in historical["case_ids"])])
    return pool, list(rows.values())


def freeze_inputs(db, artifact_id, expected_hash, option_ids):
    if (not isinstance(option_ids, list) or not 1 <= len(option_ids) <= 2
            or len(set(option_ids)) != len(option_ids) or any(not isinstance(value, str) for value in option_ids)):
        raise ValueError("scenario_selection_invalid")
    saved, _ = read_baseline(db, artifact_id, expected_hash, current=True)
    catalog = {option["id"]: option for option in _catalog(db, saved)}
    if any(identifier not in catalog for identifier in option_ids):
        raise ValueError("scenario_option_unavailable")
    content, variants = saved["content"], []
    for identifier in option_ids:
        option = deepcopy(catalog[identifier])
        pool, evidence = deepcopy(content["pool"]), deepcopy(content["result"]["scoring_evidence"])
        if option["kind"] == "production_period":
            pool, evidence = _production_variant(db, content, option)
        elif option["kind"] == "extra_entrance_exclusion":
            selected = option["parameters"]
            for asset in pool["assets"]:
                if asset["asset_id"] != selected["asset_id"]:
                    continue
                for entry in asset["entrances"]:
                    if (entry["source_id"], entry["feature_id"], entry["review_id"]) == (
                            selected["source_id"], selected["feature_id"], selected["review_id"]):
                        entry.update(eligible=False, reason="scenario_extra_exclusion")
        elif option["kind"] == "reference_vehicle":
            parameters = option["parameters"]
            entries = verified_entrances(db, assets={row["asset_id"]: row for row in pool["assets"]},
                network_id=parameters["network_id"], analysis_at=_at(content["calculation"]["analysis_at"]),
                vehicle=VehicleAssumption.model_validate(parameters["vehicle"]))
            for asset in pool["assets"]:
                # Same registered entrances only; a scenario does not discover new targets.
                originals = {(row["source_id"], row["feature_id"], row["review_id"]) for row in asset["entrances"]}
                asset["entrances"] = [row for row in entries.get(asset["asset_id"], []) if
                    (row["source_id"], row["feature_id"], row["review_id"]) in originals]
        variants.append({"option": option, "assets": pool["assets"], "evidence": evidence})
    return {"schema_version": VERSION, "artifact_id": saved["id"], "artifact_sha256": saved["content_sha256"],
        "result_id": content["result_id"], "result_sha256": content["content_sha256"],
        "pool_sha256": content["pool"]["input_sha256"], "known_at": content["pool"]["production_known_at"],
        "calculation": deepcopy(content["calculation"]), "algorithm_versions": deepcopy(content["algorithm_versions"]),
        "variants": variants, "boundary": BOUNDARY}


def authorize_inputs(db, inputs, *, current=False):
    saved, source = read_baseline(db, inputs["artifact_id"], inputs["artifact_sha256"], current=current)
    content = saved["content"]
    if (inputs.get("schema_version") != VERSION or content["pool"]["input_sha256"] != inputs["pool_sha256"]
            or content["calculation"] != inputs["calculation"] or content["algorithm_versions"] != inputs["algorithm_versions"]
            or content["content_sha256"] != inputs["result_sha256"] or content["result_id"] != inputs["result_id"]):
        raise ValueError("scenario_inputs_changed")
    for variant in inputs["variants"]:
        if [row["asset_id"] for row in variant["assets"]] != [row["asset_id"] for row in content["pool"]["assets"]]:
            raise ValueError("scenario_candidates_changed")
        for asset in variant["assets"]:
            if asset["production_context"].get("schema_version") == "facility-temporal-7.3-1":
                validate_temporal_access(db, asset["production_context"])
        if variant["option"]["kind"] == "reference_vehicle":
            parameters = variant["option"]["parameters"]
            binding = resolve_network(db, parameters["network_id"], analysis_at=_at(inputs["calculation"]["analysis_at"]),
                                      vehicle=VehicleAssumption.model_validate(parameters["vehicle"]))
            if binding.graph_sha256 != parameters["graph_sha256"]:
                raise ValueError("scenario_graph_changed")
        if variant["option"]["kind"] == "extra_road_exclusion":
            from app.services.road_scenario_networks import eligible_exclusion_options
            registered = eligible_exclusion_options(db, inputs["calculation"]["network_id"],
                analysis_at=_at(inputs["calculation"]["analysis_at"]),
                vehicle=VehicleAssumption.model_validate(inputs["calculation"]["vehicle"]))
            parameters = variant["option"]["parameters"]
            if not any({key: value for key, value in item.items() if key not in {"label", "evidence_refs"}} == parameters for item in registered):
                raise PermissionError("scenario_road_source_changed")
    return content, source


def summarize_scenario(pool, evidence, option, calculation, *, execution="reused_frozen_road_evidence"):
    rows = [FacilityEvidence(**{**row, "attribute_refs": tuple(row["attribute_refs"])}) for row in evidence]
    ranking = rank_facilities(rows, recall_complete=pool["coverage"]["complete"])
    ranking["scoring_evidence"] = [asdict(row) for row in rows]
    unresolved = sum(row.road_state not in {"calculated", "restricted"} for row in rows)
    # An explicitly excluded entrance is a known condition, not unfinished
    # calculation. Preserve distinct unknown/no-path/service-failure rows.
    coverage = {**ranking["coverage"], "unresolved": unresolved,
                "excluded": sum(row.road_state == "restricted" for row in rows),
                "complete": pool["coverage"]["complete"] and unresolved == 0}
    comparison = build_condition_comparison(pool, ranking)
    for row in comparison["rows"]:
        for condition in row["conditions"]:
            if option["kind"] == "production_period":
                condition["reason"] = condition["reason"].replace("完整案发时间", "所选资料期间").replace("案发区间", "所选资料期间").replace("案发时点", "所选资料时点")
            if condition["key"] == "road":
                condition["evidence_refs"] = sorted(set([*condition["evidence_refs"],
                    f"road_network:{calculation['network_id']}@graph:{calculation['graph_sha256']}",
                    *option.get("evidence_refs", [])]))
                if option["kind"] == "extra_entrance_exclusion" and row["asset_id"] == option["parameters"]["asset_id"]:
                    condition["reason"] += "；仅不使用指定入口作为目标连接，未修改真实入口状态，也未模拟门禁关闭对穿行路网的影响"
    return {"id": option["id"], "kind": option["kind"], "label": option["label"],
        "parameters": option.get("parameters", {}), "evidence_refs": option.get("evidence_refs", []),
        "calculation": calculation, "execution": execution,
        "source_versions": {**pool["versions"], "scenario_data_sha256": digest({"assets": pool["assets"], "evidence": evidence,
                            "option": option, "calculation": calculation})},
        "state": "completed" if coverage["complete"] else "partial",
        "coverage": coverage, "rows": comparison["rows"], "candidates": ranking["candidates"],
        "boundary": BOUNDARY}


def exclude_frozen_entrance(content, variant):
    """All entrance distances were calculated before ranking; do not reroute unchanged inputs."""
    selected = variant["option"]["parameters"]
    rows = deepcopy(variant["evidence"])
    original = next(item for item in content["pool"]["assets"] if item["asset_id"] == selected["asset_id"])
    entries = [item for item in original["entrances"] if item["eligible"]]
    outcomes = next((item["entries"] for item in content["result"]["entrance_results"] if item["asset_id"] == selected["asset_id"]), [])
    if len(outcomes) != len(entries):
        raise ValueError("scenario_entrance_evidence_incomplete")
    remaining = [result for entry, result in zip(entries, outcomes) if
                 (entry["source_id"], entry["feature_id"], entry["review_id"]) !=
                 (selected["source_id"], selected["feature_id"], selected["review_id"])]
    row = next(item for item in rows if item["asset_id"] == selected["asset_id"])
    if not remaining:
        row.update(road_state="restricted", road_distance_m=None, passage_allowed=False)
    elif any(result["state"] not in {"calculated", "no_path_found"} for result in remaining):
        row.update(road_state="not_calculated", road_distance_m=None)
    else:
        distances = [result["distance_m"] for result in remaining if result["state"] == "calculated"]
        row.update(road_state="calculated" if distances else "no_path_found", road_distance_m=min(distances) if distances else None)
    return rows


def combine(inputs, scenarios):
    by_scenario = [{row["asset_id"]: row for row in scenario["rows"]} for scenario in scenarios]
    observations = []
    for base in scenarios[0]["rows"]:
        rows = [items[base["asset_id"]] for items in by_scenario]
        states = {row["eligibility"] for row in rows}
        classification = ("insufficient_data" if "unresolved" in states else
            "retained_across_scenarios" if states == {"retained"} else
            "excluded_in_all" if states == {"excluded"} else "condition_dependent")
        changed = sorted({condition["key"] for row in rows[1:] for condition in row["conditions"]
            if any(prior["key"] == condition["key"] and (prior["state"], prior["value"]) != (condition["state"], condition["value"])
                   for prior in rows[0]["conditions"])})
        observations.append({"asset_id": base["asset_id"], "name": base["name"], "classification": classification,
            "changed_conditions": changed, "ranks": [{"scenario_id": scenario["id"], "rank": row["rank"],
                "eligibility": row["eligibility"]} for scenario, row in zip(scenarios, rows)],
            "reason": "；".join([*( ["声明条件影响：" + "、".join(changed)] if changed else ["已比较条件未改变列出的依据"]),
                "名次同时受本固定候选池相对顺序影响；未知、服务失败或未取得路径不表示现实中不可达"]),
            "evidence_refs": sorted({ref for row in rows for condition in row["conditions"] for ref in condition["evidence_refs"]})})
    return {"schema_version": VERSION, "artifact_id": inputs["artifact_id"], "artifact_sha256": inputs["artifact_sha256"],
        "result_id": inputs["result_id"], "result_sha256": inputs["result_sha256"],
        "state": "completed" if all(row["state"] == "completed" for row in scenarios) else "partial",
        "frozen": {"pool_sha256": inputs["pool_sha256"], "known_at": inputs["known_at"],
                   "algorithm_versions": inputs["algorithm_versions"], "calculation": inputs["calculation"]},
        "scenarios": scenarios, "observations": observations, "execution_task_created": False, "boundary": BOUNDARY}
