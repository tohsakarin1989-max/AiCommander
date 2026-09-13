"""Frozen-input facility comparison; road evidence precedes final top-three.

Only server-assembled, authorized evidence belongs here. This scorer neither
queries data nor grants access; all restrictions must be applied by routing.
The v3.4 implementation remains unchanged for historical evaluation.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


VERSION = "facility-roads-5.2.0-1"
ROAD_STATES = frozenset({"calculated", "no_path_found", "entrance_unknown", "restricted",
                         "permission_unknown", "network_missing", "calculation_failed", "not_calculated"})
MATCH_STATES = frozenset({"matched", "different", "unknown"})


def _nonnegative(value: object) -> bool:
    return type(value) in (float, int) and math.isfinite(value) and value >= 0


@dataclass(frozen=True)
class FacilityEvidence:
    asset_id: int
    evidence_ref: str
    straight_distance_m: float
    road_state: str
    road_distance_m: float | None = None
    entrance_verified: bool = False
    passage_allowed: bool | None = None
    oil_match: str = "unknown"
    facility_match: str = "unknown"
    production_match: str = "unknown"
    historical_match: str = "unknown"
    attribute_refs: tuple[str, ...] = ()

    def __post_init__(self):
        if (type(self.asset_id) is not int or self.asset_id <= 0
                or not isinstance(self.evidence_ref, str) or not self.evidence_ref):
            raise ValueError("invalid_facility_identity")
        if (not _nonnegative(self.straight_distance_m) or not isinstance(self.road_state, str)
                or self.road_state not in ROAD_STATES):
            raise ValueError("invalid_facility_road_evidence")
        if type(self.entrance_verified) is not bool or (self.passage_allowed is not None and type(self.passage_allowed) is not bool):
            raise ValueError("invalid_facility_permission_evidence")
        matches = (self.oil_match, self.facility_match, self.production_match, self.historical_match)
        if any(not isinstance(value, str) or value not in MATCH_STATES for value in matches):
            raise ValueError("invalid_facility_attribute_match")
        if any(value != "unknown" for value in matches) and not self.attribute_refs:
            raise ValueError("facility_attribute_evidence_required")
        if not isinstance(self.attribute_refs, tuple) or any(not isinstance(ref, str) or not ref for ref in self.attribute_refs):
            raise ValueError("invalid_facility_attribute_references")
        if self.road_state == "calculated":
            if not _nonnegative(self.road_distance_m):
                raise ValueError("road_distance_required")
        elif self.road_distance_m is not None:
            raise ValueError("unavailable_road_distance_must_be_null")


def rank_facilities(evidence: list[FacilityEvidence], *, recall_complete: bool) -> dict:
    """A score is rule support, never a probability or a crime risk score."""
    if len(evidence) > 100 or len({item.asset_id for item in evidence}) != len(evidence):
        raise ValueError("facility_pool_limit_or_duplicate")
    if type(recall_complete) is not bool:
        raise ValueError("invalid_recall_completeness")
    nearest = {item.asset_id: rank for rank, item in enumerate(
        sorted(evidence, key=lambda row: (row.straight_distance_m, row.asset_id)), 1)}
    ranked, unresolved = [], []
    for item in evidence:
        # Permission and entrance are hard eligibility conditions, never penalties.
        state = item.road_state
        if item.passage_allowed is False:
            state = "restricted"
        elif state in {"calculated", "not_calculated"}:
            if not item.entrance_verified:
                state = "entrance_unknown"
            elif item.passage_allowed is None:
                state = "permission_unknown"
        if state != "calculated":
            unresolved.append({"asset_id": item.asset_id, "state": state,
                               "road_distance_m": None, "score": None})
            continue
        km = item.road_distance_m / 1000
        components = {"road_distance": round(45 / (1 + km / 5), 4)}
        reasons = [f"可信入口已知条件下参考道路距离 {km:.2f} 公里"]
        counter, gaps = ["道路可达与属性相似不证明该设施为实际来源"], []
        for field, label, weight in (("oil_match", "油品", 20), ("facility_match", "设施用途", 15),
                                     ("production_match", "生产条件", 10), ("historical_match", "历史条件", 10)):
            match = getattr(item, field)
            components[field] = weight if match == "matched" else 0
            if match == "matched":
                reasons.append(f"{label}有来源支持的条件相符")
            elif match == "different":
                counter.append(f"{label}存在已记录的差异")
            else:
                gaps.append(f"{label}资料尚不足，不按相符处理")
        # Endpoints may be slightly snapped by the router; do not manufacture
        # a precise detour ratio for near-zero distances.
        detour = round(item.road_distance_m / item.straight_distance_m, 3) if item.straight_distance_m >= 100 else None
        if detour is not None and detour >= 2:
            counter.append(f"参考道路长度约为直线距离的 {detour:.1f} 倍，存在明显绕行")
        ranked.append({"asset_id": item.asset_id, "score": round(sum(components.values()), 4),
                       "score_kind": "rule_support_not_probability", "components": components,
                       "straight_distance_m": item.straight_distance_m, "road_distance_m": item.road_distance_m,
                       "detour_ratio": detour, "distance_only_rank": nearest[item.asset_id],
                       "supporting_evidence": reasons, "counter_evidence": counter,
                       "information_gaps": gaps, "evidence_refs": [item.evidence_ref, *item.attribute_refs],
                       "is_official_fact": False})
    ranked.sort(key=lambda item: (-item["score"], item["road_distance_m"], item["asset_id"]))
    for rank, item in enumerate(ranked, 1):
        item["rank"] = rank
        item["rank_change_from_distance"] = item["distance_only_rank"] - rank
    return {"algorithm_version": VERSION, "candidates": ranked[:3], "unresolved": unresolved,
            "coverage": {"recalled": len(evidence), "compared": len(ranked),
                         "unresolved": len(unresolved), "recall_complete": recall_complete,
                         "complete": recall_complete and not unresolved},
            "boundary": "仅比较已召回的授权设施及已知通行条件，不代表全域最优、案发时实际路线或犯罪风险概率。"}
