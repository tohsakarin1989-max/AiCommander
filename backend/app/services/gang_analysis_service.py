"""
相似条件组分析服务。

本模块保留原有 GangAnalysisService 类名和 /gangs API 以兼容旧前端调用，
但业务语义已收敛为“已侦破涉油案件的相似作案条件聚类”。同人、同车
只作为重复录入或同案拆分核验线索，不作为跨案团伙强信号。
"""
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set, Tuple
from collections import defaultdict
import json

from app.models.case import Case
from app.utils.logger import logger


class GangAnalysisService:
    """相似条件组分析服务类"""

    @staticmethod
    def extract_case_features(case: Case) -> Dict:
        """从案件中提取特征用于相似条件组分析"""
        features = {
            "case_id": case.id,
            "case_number": case.case_number,
            "occurred_time": case.occurred_time.isoformat() if case.occurred_time else None,
            "hour_of_day": case.occurred_time.hour if case.occurred_time else None,
            "day_of_week": case.occurred_time.weekday() if case.occurred_time else None,
            "location": case.location,
            "latitude": case.latitude,
            "longitude": case.longitude,
            "case_type": case.case_type,
            "modus_operandi": case.modus_operandi,
            "oil_type": case.oil_type,
            "oil_nature": case.oil_nature,
            "facility_type": case.facility_type,
            "source_type": case.source_type,
            "report_unit": case.report_unit,
            "operation_role": case.operation_role,
            "quality_score": case.quality_score,
            "quality_level": case.quality_level,
            "involved_persons": case.involved_persons or [],
            "vehicle_info": case.vehicle_info or {},
            "structured_persons": [],
            "structured_vehicles": [],
        }

        try:
            features["structured_persons"] = [
                {
                    "name": p.name,
                    "id_number": p.id_number,
                    "home_address": p.home_address,
                    "role": p.role,
                    "handling_status": p.handling_status,
                }
                for p in (case.persons or [])
            ]
            features["structured_vehicles"] = [
                {
                    "plate_number": v.plate_number,
                    "vehicle_type": v.vehicle_type,
                    "color": v.color,
                    "brand": v.brand,
                    "model": v.model,
                    "handling_status": v.handling_status,
                    "transferred_to_police": v.transferred_to_police,
                }
                for v in (case.vehicles or [])
            ]
        except Exception:
            # 兼容脱离 Session 的 Case 对象；已有 JSON 字段仍可参与分析。
            pass

        # 从预处理特征中提取更多信息
        if case.features and isinstance(case.features, dict):
            actors = case.features.get("actors", {})
            if actors:
                facts = actors.get("facts", {})
                features["known_roles"] = facts.get("known_roles", [])
                features["known_vehicles"] = facts.get("known_vehicles", [])

            modus = case.features.get("modus", {})
            if modus:
                features["modus_tools"] = modus.get("tools", [])
                features["time_pattern"] = modus.get("time_pattern", [])

        return features

    @staticmethod
    def calculate_case_similarity(case1_features: Dict, case2_features: Dict) -> float:
        """
        计算两个案件的相似度（0-1）

        必须满足至少一个稳定条件锚点才会继续计算：
        - 地理距离 ≤ 5 km（空间关联）
        - 作案手法相似
        - 目标设施相同且来源/油品/责任单位等管理画像相近

        未满足时直接返回 0，避免仅凭案件类型相同就将
        全省同类案件链接成一个大条件组。同人同车不参与加权，
        只应由案件研判工作台作为重复录入或同案拆分提示。
        """
        from app.utils.geo import haversine_km

        # 地理锚定（≤ 5 km）
        has_geo_anchor = False
        geo_distance_km: Optional[float] = None
        if (case1_features.get("latitude") and case1_features.get("longitude") and
                case2_features.get("latitude") and case2_features.get("longitude")):
            geo_distance_km = haversine_km(
                case1_features["latitude"], case1_features["longitude"],
                case2_features["latitude"], case2_features["longitude"]
            )
            has_geo_anchor = geo_distance_km <= 5.0

        def _bigram_similarity(s1: str, s2: str) -> float:
            """计算两字符串的 bigram 集合 Jaccard 相似度"""
            if not s1 or not s2:
                return 0.0
            b1 = {s1[i:i+2] for i in range(len(s1)-1)} if len(s1) > 1 else {s1}
            b2 = {s2[i:i+2] for i in range(len(s2)-1)} if len(s2) > 1 else {s2}
            if not b1 or not b2:
                return 0.0
            return len(b1 & b2) / len(b1 | b2)

        modus1 = case1_features.get("modus_operandi", "")
        modus2 = case2_features.get("modus_operandi", "")
        modus_sim = _bigram_similarity(modus1, modus2) if modus1 and modus2 else 0.0
        has_modus_anchor = modus_sim >= 0.5

        shared_context_count = sum(
            1
            for field in ("source_type", "oil_nature", "report_unit")
            if (
                case1_features.get(field)
                and case2_features.get(field)
                and case1_features.get(field) == case2_features.get(field)
            )
        )
        has_facility_context = bool(
            case1_features.get("facility_type")
            and case1_features.get("facility_type") == case2_features.get("facility_type")
            and shared_context_count >= 1
        )

        if not (has_geo_anchor or has_modus_anchor or has_facility_context):
            return 0.0

        # ── 加权相似度计算 ────────────────────────────────────
        similarity_scores = []
        weights = []

        # 1. 时间模式
        if case1_features.get("hour_of_day") is not None and case2_features.get("hour_of_day") is not None:
            hour_diff = abs(case1_features["hour_of_day"] - case2_features["hour_of_day"])
            similarity_scores.append(1 - min(hour_diff, 12) / 12)
            weights.append(0.1)

        # 2. 作案手法
        if modus1 and modus2:
            similarity_scores.append(modus_sim)
            weights.append(0.25)

        # 3. 目标设施类型
        facility1 = case1_features.get("facility_type", "")
        facility2 = case2_features.get("facility_type", "")
        if facility1 and facility2:
            similarity_scores.append(1.0 if facility1 == facility2 else 0.0)
            weights.append(0.15)

        # 4. 地理位置（使用已算出的距离）
        if geo_distance_km is not None:
            geo_sim = max(0.0, 1 - geo_distance_km / 10)
            similarity_scores.append(geo_sim)
            weights.append(0.2)

        # 5. 线索来源、原油性质、责任单位等管理画像
        if case1_features.get("source_type") and case2_features.get("source_type"):
            similarity_scores.append(1.0 if case1_features["source_type"] == case2_features["source_type"] else 0.0)
            weights.append(0.05)
        if case1_features.get("oil_nature") and case2_features.get("oil_nature"):
            similarity_scores.append(1.0 if case1_features["oil_nature"] == case2_features["oil_nature"] else 0.0)
            weights.append(0.08)
        if case1_features.get("report_unit") and case2_features.get("report_unit"):
            similarity_scores.append(1.0 if case1_features["report_unit"] == case2_features["report_unit"] else 0.0)
            weights.append(0.05)

        if not similarity_scores:
            return 0.0
        return sum(s * w for s, w in zip(similarity_scores, weights)) / sum(weights)

    @staticmethod
    def identify_gangs(
        db: Session,
        case_ids: Optional[List[int]] = None,
        min_similarity: float = 0.5,
        min_cases: int = 2,
        time_window_days: int = 90
    ) -> List[Dict]:
        """
        识别相似条件组

        Args:
            case_ids: 指定分析的案件ID列表（为空则分析所有案件）
            min_similarity: 最小相似度阈值
            min_cases: 条件组最少案件数
            time_window_days: 时间窗口（天）

        Returns:
            条件组列表，每个组包含案件ID、特征画像等
        """
        # 获取案件
        query = db.query(Case)
        if case_ids:
            query = query.filter(Case.id.in_(case_ids))

        cutoff_date = datetime.utcnow() - timedelta(days=time_window_days)
        query = query.filter(Case.occurred_time >= cutoff_date)

        cases = query.all()
        if len(cases) < min_cases:
            return []

        # 提取特征
        case_features = {c.id: GangAnalysisService.extract_case_features(c) for c in cases}

        # 构建相似度图
        similarity_graph: Dict[int, List[Tuple[int, float]]] = defaultdict(list)
        case_list = list(case_features.keys())

        for i in range(len(case_list)):
            for j in range(i + 1, len(case_list)):
                id1, id2 = case_list[i], case_list[j]
                sim = GangAnalysisService.calculate_case_similarity(
                    case_features[id1], case_features[id2]
                )
                if sim >= min_similarity:
                    similarity_graph[id1].append((id2, sim))
                    similarity_graph[id2].append((id1, sim))

        # 使用连通分量算法识别相似条件组
        visited: Set[int] = set()
        gangs = []

        def dfs(case_id: int, gang: List[int]):
            """深度优先搜索连通分量"""
            if case_id in visited:
                return
            visited.add(case_id)
            gang.append(case_id)
            for neighbor, _ in similarity_graph[case_id]:
                dfs(neighbor, gang)

        for case_id in case_list:
            if case_id not in visited and case_id in similarity_graph:
                gang = []
                dfs(case_id, gang)
                if len(gang) >= min_cases:
                    # 生成相似条件组画像
                    gang_profile = GangAnalysisService._generate_gang_profile(
                        [case_features[cid] for cid in gang]
                    )
                    gang_profile["case_ids"] = gang
                    gang_profile["case_count"] = len(gang)
                    gangs.append(gang_profile)

        # 按案件数量排序
        gangs.sort(key=lambda g: g["case_count"], reverse=True)

        return gangs

    @staticmethod
    def _generate_gang_profile(case_features_list: List[Dict]) -> Dict:
        """生成相似条件组画像"""
        profile = {
            "active_hours": [],
            "active_days": [],
            "preferred_locations": [],
            "modus_operandi": [],
            "target_facilities": [],
            "known_persons": [],
            "known_vehicles": [],
            "source_types": [],
            "oil_natures": [],
            "report_units": [],
            "quality": {
                "average_score": 0,
                "low_quality_case_ids": [],
            },
            "oil_types": [],
            "geographic_center": None,
            "time_span_days": 0,
            "risk_score": 0,
        }

        # 统计时间模式
        hours = defaultdict(int)
        days = defaultdict(int)
        for f in case_features_list:
            if f.get("hour_of_day") is not None:
                hours[f["hour_of_day"]] += 1
            if f.get("day_of_week") is not None:
                days[f["day_of_week"]] += 1

        profile["active_hours"] = sorted(hours.keys(), key=lambda h: hours[h], reverse=True)[:3]
        profile["active_days"] = sorted(days.keys(), key=lambda d: days[d], reverse=True)[:3]

        # 统计地点
        locations = defaultdict(int)
        for f in case_features_list:
            if f.get("location"):
                locations[f["location"]] += 1
        profile["preferred_locations"] = sorted(
            locations.keys(), key=lambda l: locations[l], reverse=True
        )[:5]

        # 统计作案手法
        modus_counts = defaultdict(int)
        for f in case_features_list:
            if f.get("modus_operandi"):
                modus_counts[f["modus_operandi"]] += 1
        profile["modus_operandi"] = sorted(
            modus_counts.keys(), key=lambda m: modus_counts[m], reverse=True
        )[:3]

        # 统计目标设施
        facilities = defaultdict(int)
        for f in case_features_list:
            if f.get("facility_type"):
                facilities[f["facility_type"]] += 1
        profile["target_facilities"] = sorted(
            facilities.keys(), key=lambda t: facilities[t], reverse=True
        )[:3]

        # 收集涉案人员
        persons_set = set()
        for f in case_features_list:
            persons = (f.get("involved_persons") or []) + (f.get("structured_persons") or [])
            if persons:
                for p in persons:
                    if isinstance(p, dict) and p.get("name"):
                        persons_set.add(p["name"])
        profile["known_persons"] = list(persons_set)[:10]

        # 收集车辆信息
        vehicles = []
        for f in case_features_list:
            if f.get("vehicle_info"):
                v = f["vehicle_info"]
                if isinstance(v, dict) and v.get("plate_number"):
                    vehicles.append(v["plate_number"])
            if f.get("known_vehicles"):
                for v in f["known_vehicles"]:
                    if isinstance(v, dict) and v.get("plate"):
                        vehicles.append(v["plate"])
            if f.get("structured_vehicles"):
                for v in f["structured_vehicles"]:
                    if isinstance(v, dict) and v.get("plate_number"):
                        vehicles.append(v["plate_number"])
        profile["known_vehicles"] = list(set(vehicles))[:10]

        for field, target in (
            ("source_type", "source_types"),
            ("oil_nature", "oil_natures"),
            ("report_unit", "report_units"),
        ):
            counts = defaultdict(int)
            for f in case_features_list:
                if f.get(field):
                    counts[f[field]] += 1
            profile[target] = sorted(counts.keys(), key=lambda t: counts[t], reverse=True)[:5]

        # 统计油品类型
        oil_types = defaultdict(int)
        for f in case_features_list:
            if f.get("oil_type"):
                oil_types[f["oil_type"]] += 1
        profile["oil_types"] = sorted(
            oil_types.keys(), key=lambda t: oil_types[t], reverse=True
        )[:3]

        quality_scores = [
            f["quality_score"]
            for f in case_features_list
            if isinstance(f.get("quality_score"), (int, float))
        ]
        if quality_scores:
            profile["quality"] = {
                "average_score": round(sum(quality_scores) / len(quality_scores), 2),
                "low_quality_case_ids": [
                    f["case_id"]
                    for f in case_features_list
                    if isinstance(f.get("quality_score"), (int, float)) and f["quality_score"] < 60
                ],
            }

        # 计算地理中心
        lats = [f["latitude"] for f in case_features_list if f.get("latitude")]
        lngs = [f["longitude"] for f in case_features_list if f.get("longitude")]
        if lats and lngs:
            profile["geographic_center"] = {
                "latitude": sum(lats) / len(lats),
                "longitude": sum(lngs) / len(lngs),
            }

        # 计算时间跨度（统一去除时区）
        def _strip_tz(dt):
            return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt

        times = []
        for f in case_features_list:
            if f.get("occurred_time"):
                try:
                    times.append(_strip_tz(datetime.fromisoformat(f["occurred_time"])))
                except Exception:
                    pass
        if times:
            profile["time_span_days"] = (max(times) - min(times)).days

        # 计算风险评分（基于案件数量、活跃度等）
        case_count = len(case_features_list)
        recency_bonus = 20 if profile["time_span_days"] < 30 else 10 if profile["time_span_days"] < 60 else 0
        profile["risk_score"] = min(100, case_count * 15 + recency_bonus)

        return profile

    @staticmethod
    def get_gang_relations(gang_profile: Dict) -> List[Dict]:
        """
        生成条件组关系图数据

        返回节点和边的列表，用于可视化
        """
        nodes = []
        edges = []

        # 添加案件节点
        for case_id in gang_profile.get("case_ids", []):
            nodes.append({
                "id": f"case_{case_id}",
                "type": "case",
                "label": f"案件 #{case_id}",
            })

        # 添加人员节点和关系
        for person in gang_profile.get("known_persons", []):
            person_id = f"person_{person}"
            nodes.append({
                "id": person_id,
                "type": "person",
                "label": person,
            })

        # 添加车辆节点
        for vehicle in gang_profile.get("known_vehicles", []):
            vehicle_id = f"vehicle_{vehicle}"
            nodes.append({
                "id": vehicle_id,
                "type": "vehicle",
                "label": vehicle,
            })

        # 添加地点节点
        for location in gang_profile.get("preferred_locations", [])[:3]:
            location_id = f"location_{hash(location) % 10000}"
            nodes.append({
                "id": location_id,
                "type": "location",
                "label": location[:20] + "..." if len(location) > 20 else location,
            })

        return {"nodes": nodes, "edges": edges}

    @staticmethod
    def analyze_gang_timeline(db: Session, case_ids: List[int]) -> List[Dict]:
        """分析条件组案件时间线"""
        cases = db.query(Case).filter(Case.id.in_(case_ids)).order_by(Case.occurred_time).all()

        timeline = []
        for case in cases:
            timeline.append({
                "case_id": case.id,
                "case_number": case.case_number,
                "occurred_time": case.occurred_time.isoformat() if case.occurred_time else None,
                "location": case.location,
                "case_type": case.case_type,
                "modus_operandi": case.modus_operandi,
            })

        return timeline

    @staticmethod
    def get_activity_heatmap(case_ids: List[int], db: Session) -> Dict:
        """
        生成条件组案件时间热力图数据（7天 × 24小时）

        weekday 映射：Python weekday() 0=周一…6=周日，转换为显示顺序 0=周日…6=周六

        返回：
        {
          "matrix": [[count, ...], ...]   # shape: 7×24，matrix[weekday][hour]
          "peak_cell": {"weekday": int, "hour": int, "count": int}
          "total_cases": int
          "day_totals": [int, ...]         # 长度 7，每天总案件数
          "hour_totals": [int, ...]        # 长度 24，每小时总案件数
        }
        """
        # 初始化 7×24 矩阵（0=周日, 1=周一, ..., 6=周六）
        matrix: List[List[int]] = [[0] * 24 for _ in range(7)]

        cases = db.query(Case).filter(Case.id.in_(case_ids)).all()
        for case in cases:
            if case.occurred_time is None:
                continue
            # Python weekday: 0=周一, 6=周日 → 转换为 0=周日, 1=周一, ..., 6=周六
            py_wd = case.occurred_time.weekday()
            display_wd = (py_wd + 1) % 7
            hour = case.occurred_time.hour
            matrix[display_wd][hour] += 1

        # 计算各维度统计
        day_totals = [sum(matrix[d]) for d in range(7)]
        hour_totals = [sum(matrix[d][h] for d in range(7)) for h in range(24)]

        # 找到峰值格
        peak_weekday, peak_hour, peak_count = 0, 0, 0
        for d in range(7):
            for h in range(24):
                if matrix[d][h] > peak_count:
                    peak_count = matrix[d][h]
                    peak_weekday = d
                    peak_hour = h

        return {
            "matrix": matrix,
            "peak_cell": {"weekday": peak_weekday, "hour": peak_hour, "count": peak_count},
            "total_cases": len(cases),
            "day_totals": day_totals,
            "hour_totals": hour_totals,
        }

    @staticmethod
    def find_cross_gang_persons(gangs: List[Dict]) -> List[Dict]:
        """
        已侦破案件中的同人重复出现不再推断为跨组中间人或销赃网络。

        保留该方法仅为兼容旧 API，前端会收到空列表。
        """
        return []
