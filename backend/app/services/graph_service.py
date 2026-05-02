"""
案件模式图谱构建服务
支持作案手法、案件类型、地理距离、时间接近等条件关系分析。
同人同车只作为重复录入或同案拆分核验提示，不单独形成跨案规律。
"""
from typing import Dict, Any, List, Set
from datetime import timedelta
from sqlalchemy.orm import Session

from app.services.case_service import CaseService
from app.utils.geo import haversine_km


# 关联类型优先级（权重从高到低）
_RELATION_PRIORITY = ["modus", "geo", "time", "type", "duplicate_anchor"]


def _bigram_similarity(s1: str, s2: str) -> float:
    """计算两字符串的 bigram 集合 Jaccard 相似度"""
    if not s1 or not s2:
        return 0.0
    b1 = {s1[i:i+2] for i in range(len(s1) - 1)} if len(s1) > 1 else {s1}
    b2 = {s2[i:i+2] for i in range(len(s2) - 1)} if len(s2) > 1 else {s2}
    if not b1 or not b2:
        return 0.0
    return len(b1 & b2) / len(b1 | b2)


def _extract_plates(case) -> Set[str]:
    """从案件提取所有车牌号集合"""
    plates: Set[str] = set()
    # 直接车辆信息字段
    if isinstance(case.vehicle_info, dict) and case.vehicle_info.get("plate_number"):
        plates.add(case.vehicle_info["plate_number"])
    # features.actors.facts.known_vehicles
    if isinstance(case.features, dict):
        actors = case.features.get("actors", {})
        if isinstance(actors, dict):
            facts = actors.get("facts", {})
            if isinstance(facts, dict):
                for veh in (facts.get("known_vehicles") or []):
                    if isinstance(veh, dict) and veh.get("plate"):
                        plates.add(veh["plate"])
    return plates


def _extract_person_names(case) -> Set[str]:
    """从案件 involved_persons 提取姓名集合"""
    names: Set[str] = set()
    for person in (case.involved_persons or []):
        if isinstance(person, dict) and person.get("name"):
            names.add(person["name"])
    return names


def _dominant_relation_type(relation_types: List[str]) -> str:
    """按优先级取最高权重的关联类型"""
    for rtype in _RELATION_PRIORITY:
        if rtype in relation_types:
            return rtype
    return relation_types[0] if relation_types else "type"


class GraphService:
    @staticmethod
    def build_serial_graph(
        db: Session,
        case_ids: List[int],
        radius_km: float = 2.0,
    ) -> Dict[str, Any]:
        cases = CaseService.get_cases_by_ids(db, case_ids)

        # 构建节点，新增前端展示所需字段
        nodes = [
            {
                "id": c.id,
                "case_number": c.case_number,
                "case_type": c.case_type,
                "location": c.location,
                "latitude": c.latitude,
                "longitude": c.longitude,
                "modus_operandi": c.modus_operandi,
                "occurred_time": c.occurred_time.isoformat() if c.occurred_time else None,
                "oil_type": c.oil_type,
                "oil_volume": c.oil_volume,
                "facility_type": c.facility_type,
                "involved_persons_count": len(c.involved_persons or []),
                "has_vehicle": bool(c.vehicle_info),
            }
            for c in cases
        ]

        edges = []
        for i in range(len(cases)):
            for j in range(i + 1, len(cases)):
                c1, c2 = cases[i], cases[j]
                reasons: List[str] = []
                score = 0.0
                relation_types: List[str] = []

                duplicate_reasons: List[str] = []

                # ── 重复锚点：共同涉案人员仅用于核验，不单独成边 ──
                names1 = _extract_person_names(c1)
                names2 = _extract_person_names(c2)
                common_names = names1 & names2
                if common_names:
                    for name in sorted(common_names):
                        duplicate_reasons.append(f"相同人员需核验: {name}")

                # ── 重复锚点：共同车辆仅用于核验，不单独成边 ─────
                plates1 = _extract_plates(c1)
                plates2 = _extract_plates(c2)
                common_plates = plates1 & plates2
                if common_plates:
                    for plate in sorted(common_plates):
                        duplicate_reasons.append(f"相同车牌需核验: {plate}")

                # ── 维度1：作案手法 bigram 相似度（>=0.5，0.35）──
                if c1.modus_operandi and c2.modus_operandi:
                    sim = _bigram_similarity(c1.modus_operandi, c2.modus_operandi)
                    if sim >= 0.5:
                        reasons.append("同手法")
                        score += 0.35
                        relation_types.append("modus")

                # ── 维度2：案件类型相同（0.2）─────────────────────
                if c1.case_type and c1.case_type == c2.case_type:
                    reasons.append("同类型")
                    score += 0.2
                    relation_types.append("type")

                # ── 维度3：地理距离（<=radius_km，0.25）──────────
                if c1.latitude and c1.longitude and c2.latitude and c2.longitude:
                    dist = haversine_km(c1.latitude, c1.longitude, c2.latitude, c2.longitude)
                    if dist <= radius_km:
                        reasons.append(f"距离{dist:.2f}km")
                        score += 0.25
                        relation_types.append("geo")

                # ── 维度4：时间接近（<=30天，0.2）────────────────
                if c1.occurred_time and c2.occurred_time:
                    delta = abs(c1.occurred_time - c2.occurred_time)
                    if delta <= timedelta(days=30):
                        days_diff = delta.days
                        reasons.append(f"时间差{days_diff}天")
                        score += 0.2
                        relation_types.append("time")

                if reasons:
                    if duplicate_reasons:
                        reasons.extend(duplicate_reasons)
                        relation_types.append("duplicate_anchor")
                    edges.append({
                        "source": c1.id,
                        "target": c2.id,
                        "reasons": reasons,
                        "score": round(min(score, 1.0), 2),
                        "relation_types": list(dict.fromkeys(relation_types)),  # 去重保序
                        "dominant_type": _dominant_relation_type(relation_types),
                    })

        # 统计信息
        stats = {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "person_links": 0,
            "vehicle_links": 0,
            "duplicate_anchor_links": len([e for e in edges if "duplicate_anchor" in e["relation_types"]]),
            "modus_links": len([e for e in edges if "modus" in e["relation_types"]]),
            "geo_links": len([e for e in edges if "geo" in e["relation_types"]]),
            "strong_links": len([e for e in edges if e["score"] >= 0.7]),
        }

        return {"nodes": nodes, "edges": edges, "stats": stats}
