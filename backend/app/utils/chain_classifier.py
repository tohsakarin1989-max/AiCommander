from typing import Any, Dict, Literal

ChainPosition = Literal["upstream", "midstream", "downstream", "unknown"]


CHAIN_POSITION_META: Dict[ChainPosition, Dict[str, str]] = {
    "upstream": {
        "label": "盗采环节",
        "color": "#ef4444",
        "shape": "hexagon",
    },
    "midstream": {
        "label": "运输环节",
        "color": "#f59e0b",
        "shape": "diamond",
    },
    "downstream": {
        "label": "囤储环节",
        "color": "#3b82f6",
        "shape": "square",
    },
    "unknown": {
        "label": "未分类",
        "color": "#94a3b8",
        "shape": "circle",
    },
}


def _facility_type_from(case: Any) -> str:
    if isinstance(case, str):
        return case
    if isinstance(case, dict):
        return str(case.get("facility_type") or "")
    return str(getattr(case, "facility_type", "") or "")


def classify_chain_position(case: Any) -> ChainPosition:
    facility_type = _facility_type_from(case).strip()
    if not facility_type:
        return "unknown"

    if "管线" in facility_type or "管道" in facility_type:
        return "upstream"
    if "油罐车" in facility_type or "罐车" in facility_type or "运输" in facility_type:
        return "midstream"
    if "油库" in facility_type or "加油站" in facility_type or "囤" in facility_type or "储" in facility_type:
        return "downstream"
    return "unknown"


def get_chain_position_meta(position: ChainPosition | str) -> Dict[str, str]:
    return CHAIN_POSITION_META.get(position, CHAIN_POSITION_META["unknown"])
