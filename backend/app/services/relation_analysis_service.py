"""
关联分析服务
用于分析事件之间的关联关系，支持区域研判
"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from app.models.event import Event, EventRelation, AreaProfile, RELATION_TYPES
from app.models.case import Case
from app.utils.geo import haversine_km, bounding_box


class RelationAnalysisService:
    """事件关联分析服务"""

    # 关联分析的默认参数
    DEFAULT_SPATIAL_RADIUS_KM = 5.0  # 空间关联半径（公里）
    DEFAULT_TIME_WINDOW_DAYS = 180   # 时间窗口（天）
    SUPPLY_CHAIN_RADIUS_KM = 10.0    # 上下游关联搜索半径

    @staticmethod
    def find_spatial_relations(
        db: Session,
        event: Event,
        radius_km: float = None,
        time_window_days: int = None
    ) -> List[Dict]:
        """
        查找与指定事件空间关联的其他事件

        Args:
            db: 数据库会话
            event: 目标事件
            radius_km: 搜索半径（公里）
            time_window_days: 时间窗口（天），None表示不限时间

        Returns:
            关联事件列表，包含距离和时间间隔信息
        """
        if not event.latitude or not event.longitude:
            return []

        radius_km = radius_km or RelationAnalysisService.DEFAULT_SPATIAL_RADIUS_KM

        # 使用边界框预筛选
        min_lat, max_lat, min_lng, max_lng = bounding_box(
            event.latitude, event.longitude, radius_km
        )

        # 构建查询
        query = db.query(Event).filter(
            Event.id != event.id,
            Event.latitude.isnot(None),
            Event.longitude.isnot(None),
            Event.latitude.between(min_lat, max_lat),
            Event.longitude.between(min_lng, max_lng)
        )

        # 添加时间窗口过滤
        if time_window_days:
            if event.occurred_time:
                time_start = event.occurred_time - timedelta(days=time_window_days)
                time_end = event.occurred_time + timedelta(days=time_window_days)
                query = query.filter(
                    Event.occurred_time.between(time_start, time_end)
                )

        nearby_events = query.all()

        # 精确距离计算和过滤
        relations = []
        for other in nearby_events:
            distance = haversine_km(
                event.latitude, event.longitude,
                other.latitude, other.longitude
            )
            if distance <= radius_km:
                time_gap = None
                if event.occurred_time and other.occurred_time:
                    time_gap = abs((event.occurred_time - other.occurred_time).days)

                relations.append({
                    "event": other,
                    "event_id": other.id,
                    "distance_km": round(distance, 2),
                    "time_gap_days": time_gap,
                    "relation_type": "spatial_cluster",
                    "confidence": RelationAnalysisService._calc_spatial_confidence(distance, radius_km),
                    "reasoning": f"与目标事件相距{distance:.1f}km，在{radius_km}km关联范围内"
                })

        return sorted(relations, key=lambda x: x["distance_km"])

    @staticmethod
    def find_supply_chain_relations(db: Session, event: Event) -> List[Dict]:
        """
        查找上下游关联（盗油点↔运输↔囤油点）

        基于业务逻辑推断事件之间的供应链关系
        """
        relations = []
        radius_km = RelationAnalysisService.SUPPLY_CHAIN_RADIUS_KM

        if not event.latitude or not event.longitude:
            return relations

        # 获取附近事件
        nearby = RelationAnalysisService.find_spatial_relations(
            db, event, radius_km=radius_km, time_window_days=180
        )

        for rel in nearby:
            other = rel["event"]
            chain_relation = None

            # 囤油点 → 查找上游（盗油点/管线打孔点）
            if event.event_type == "stash_found":
                if other.event_type in ["theft_case", "pipeline_tap", "damage_found"]:
                    chain_relation = {
                        **rel,
                        "relation_type": "supply_chain",
                        "chain_role": "upstream",
                        "confidence": 0.7 if rel["distance_km"] < 5 else 0.5,
                        "reasoning": f"囤油点与盗油点/打孔点相距{rel['distance_km']}km，可能是油源"
                    }

            # 盗油车 → 查找下游（囤油点）
            elif event.event_type == "vehicle_caught":
                if other.event_type == "stash_found":
                    chain_relation = {
                        **rel,
                        "relation_type": "supply_chain",
                        "chain_role": "downstream",
                        "confidence": 0.7 if rel["distance_km"] < 5 else 0.5,
                        "reasoning": f"盗油车抓获点与囤油点相距{rel['distance_km']}km，可能是其囤油点"
                    }
                elif other.event_type in ["theft_case", "pipeline_tap"]:
                    chain_relation = {
                        **rel,
                        "relation_type": "supply_chain",
                        "chain_role": "upstream",
                        "confidence": 0.6,
                        "reasoning": f"盗油车抓获点与盗油点相距{rel['distance_km']}km，可能是作案地点"
                    }

            # 管线打孔点 → 查找下游（囤油点、盗油车）
            elif event.event_type == "pipeline_tap":
                if other.event_type == "stash_found":
                    chain_relation = {
                        **rel,
                        "relation_type": "supply_chain",
                        "chain_role": "downstream",
                        "confidence": 0.8 if rel["distance_km"] < 5 else 0.6,
                        "reasoning": f"打孔点与囤油点相距{rel['distance_km']}km，可能是储存点"
                    }
                elif other.event_type == "vehicle_caught":
                    chain_relation = {
                        **rel,
                        "relation_type": "supply_chain",
                        "chain_role": "downstream",
                        "confidence": 0.6,
                        "reasoning": f"打孔点与盗油车抓获点相距{rel['distance_km']}km，可能是运输环节"
                    }

            if chain_relation:
                relations.append(chain_relation)

        return relations

    @staticmethod
    def find_vehicle_relations(db: Session, event: Event) -> List[Dict]:
        """
        查找车辆关联（涉及相同车辆的事件）
        """
        if not event.vehicles:
            return []

        relations = []
        event_plates = set()

        # 提取本事件的车牌
        for v in event.vehicles:
            if isinstance(v, dict) and v.get("plate"):
                event_plates.add(v["plate"])

        if not event_plates:
            return []

        # 查找涉及相同车牌的其他事件
        all_events = db.query(Event).filter(
            Event.id != event.id,
            Event.vehicles.isnot(None)
        ).all()

        for other in all_events:
            if not other.vehicles:
                continue

            other_plates = set()
            for v in other.vehicles:
                if isinstance(v, dict) and v.get("plate"):
                    other_plates.add(v["plate"])

            common_plates = event_plates & other_plates
            if common_plates:
                distance = None
                if event.latitude and event.longitude and other.latitude and other.longitude:
                    distance = haversine_km(
                        event.latitude, event.longitude,
                        other.latitude, other.longitude
                    )

                time_gap = None
                if event.occurred_time and other.occurred_time:
                    time_gap = abs((event.occurred_time - other.occurred_time).days)

                relations.append({
                    "event": other,
                    "event_id": other.id,
                    "distance_km": round(distance, 2) if distance else None,
                    "time_gap_days": time_gap,
                    "relation_type": "vehicle_link",
                    "common_plates": list(common_plates),
                    "confidence": 0.9,
                    "reasoning": f"涉及相同车辆：{', '.join(common_plates)}"
                })

        return relations

    @staticmethod
    def find_modus_relations(db: Session, event: Event) -> List[Dict]:
        """
        查找手法相似的关联（基于事件类型和描述特征）
        """
        if not event.event_type:
            return []

        relations = []

        # 查找相同类型的事件
        same_type_events = db.query(Event).filter(
            Event.id != event.id,
            Event.event_type == event.event_type
        ).all()

        for other in same_type_events:
            distance = None
            if event.latitude and event.longitude and other.latitude and other.longitude:
                distance = haversine_km(
                    event.latitude, event.longitude,
                    other.latitude, other.longitude
                )

            time_gap = None
            if event.occurred_time and other.occurred_time:
                time_gap = abs((event.occurred_time - other.occurred_time).days)

            # 同类型事件，如果还有其他相似特征，提高置信度
            confidence = 0.4
            reasoning_parts = [f"同为{event.event_type}类型事件"]

            # 检查设备相似
            if event.equipment and other.equipment:
                event_equip = set(event.equipment) if isinstance(event.equipment, list) else set()
                other_equip = set(other.equipment) if isinstance(other.equipment, list) else set()
                common_equip = event_equip & other_equip
                if common_equip:
                    confidence += 0.2
                    reasoning_parts.append(f"使用相同工具：{', '.join(common_equip)}")

            # 检查油品类型相似
            if event.oil_type and other.oil_type and event.oil_type == other.oil_type:
                confidence += 0.1
                reasoning_parts.append(f"涉及相同油品：{event.oil_type}")

            # 空间接近提高置信度
            if distance and distance < 20:
                confidence += 0.2
                reasoning_parts.append(f"空间距离较近（{distance:.1f}km）")

            relations.append({
                "event": other,
                "event_id": other.id,
                "distance_km": round(distance, 2) if distance else None,
                "time_gap_days": time_gap,
                "relation_type": "modus_match",
                "confidence": min(confidence, 1.0),
                "reasoning": "；".join(reasoning_parts)
            })

        # 按置信度排序，取置信度较高的
        return sorted(relations, key=lambda x: -x["confidence"])[:20]

    @staticmethod
    def analyze_event_relations(db: Session, event_id: int) -> Dict:
        """
        综合分析某个事件的所有关联关系

        Returns:
            包含各类关联的完整分析结果
        """
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            return {"error": "事件不存在"}

        # 收集各类关联
        spatial_relations = RelationAnalysisService.find_spatial_relations(db, event)
        supply_chain_relations = RelationAnalysisService.find_supply_chain_relations(db, event)
        vehicle_relations = RelationAnalysisService.find_vehicle_relations(db, event)
        modus_relations = RelationAnalysisService.find_modus_relations(db, event)

        # 合并去重（以 event_id 为键）
        all_relations = {}
        for rel in spatial_relations + supply_chain_relations + vehicle_relations + modus_relations:
            event_id = rel["event_id"]
            if event_id not in all_relations:
                all_relations[event_id] = {
                    "event": rel["event"],
                    "event_id": event_id,
                    "distance_km": rel.get("distance_km"),
                    "time_gap_days": rel.get("time_gap_days"),
                    "relation_types": [],
                    "max_confidence": 0,
                    "reasonings": []
                }

            all_relations[event_id]["relation_types"].append(rel["relation_type"])
            all_relations[event_id]["max_confidence"] = max(
                all_relations[event_id]["max_confidence"],
                rel.get("confidence", 0)
            )
            if rel.get("reasoning"):
                all_relations[event_id]["reasonings"].append(rel["reasoning"])

        # 转换为列表并排序
        relations_list = list(all_relations.values())
        relations_list.sort(key=lambda x: -x["max_confidence"])

        # 生成研判建议
        suggestions = RelationAnalysisService._generate_suggestions(event, relations_list)

        return {
            "event": event,
            "relations": relations_list,
            "relations_count": len(relations_list),
            "by_type": {
                "spatial_cluster": len(spatial_relations),
                "supply_chain": len(supply_chain_relations),
                "vehicle_link": len(vehicle_relations),
                "modus_match": len([r for r in modus_relations if r["confidence"] > 0.5])
            },
            "suggestions": suggestions
        }

    @staticmethod
    def _calc_spatial_confidence(distance: float, max_radius: float) -> float:
        """计算空间关联置信度（距离越近置信度越高）"""
        if distance <= 0:
            return 1.0
        return max(0.3, 1.0 - (distance / max_radius) * 0.5)

    @staticmethod
    def _generate_suggestions(event: Event, relations: List[Dict]) -> List[Dict]:
        """基于关联分析生成研判建议"""
        suggestions = []

        # 统计关联情况
        supply_chain_count = sum(1 for r in relations if "supply_chain" in r["relation_types"])
        vehicle_link_count = sum(1 for r in relations if "vehicle_link" in r["relation_types"])
        high_confidence_count = sum(1 for r in relations if r["max_confidence"] >= 0.7)

        # 建议1：存在上下游关联
        if supply_chain_count > 0:
            suggestions.append({
                "type": "investigation",
                "priority": "high",
                "title": "存在上下游关联",
                "content": f"发现{supply_chain_count}个可能的上下游关联事件，建议排查是否存在完整的盗油链条",
                "action": "扩大排查范围，寻找链条上的其他环节（油源、运输、囤积、销赃）"
            })

        # 建议2：车辆关联
        if vehicle_link_count > 0:
            suggestions.append({
                "type": "tracking",
                "priority": "high",
                "title": "发现车辆关联",
                "content": f"有{vehicle_link_count}个事件涉及相同车辆，可能是同一团伙所为",
                "action": "重点关注涉案车辆的活动轨迹和规律"
            })

        # 建议3：区域聚集
        if len(relations) >= 3:
            suggestions.append({
                "type": "patrol",
                "priority": "medium",
                "title": "区域事件聚集",
                "content": f"该事件周边发现{len(relations)}个关联事件，该区域可能是团伙活动范围",
                "action": "建议加强该区域巡逻，关注是否有团伙窝点"
            })

        # 建议4：高置信度关联
        if high_confidence_count >= 2:
            suggestions.append({
                "type": "analysis",
                "priority": "high",
                "title": "多个高置信度关联",
                "content": f"发现{high_confidence_count}个高置信度关联事件，强烈建议开展深度研判",
                "action": "建议召开专题研判会议，综合分析这些关联事件"
            })

        return suggestions

    @staticmethod
    def save_relations(db: Session, event_id: int, relations: List[Dict]) -> int:
        """
        将分析出的关联关系保存到数据库

        Returns:
            保存的关联数量
        """
        saved_count = 0
        for rel in relations:
            # 检查是否已存在
            existing = db.query(EventRelation).filter(
                or_(
                    and_(
                        EventRelation.event_a_id == event_id,
                        EventRelation.event_b_id == rel["event_id"]
                    ),
                    and_(
                        EventRelation.event_a_id == rel["event_id"],
                        EventRelation.event_b_id == event_id
                    )
                )
            ).first()

            if not existing:
                for rel_type in rel.get("relation_types", [rel.get("relation_type")]):
                    relation = EventRelation(
                        event_a_id=event_id,
                        event_b_id=rel["event_id"],
                        relation_type=rel_type,
                        confidence=rel.get("max_confidence", rel.get("confidence", 0.5)),
                        distance_km=rel.get("distance_km"),
                        time_gap_days=rel.get("time_gap_days"),
                        reasoning="; ".join(rel.get("reasonings", [rel.get("reasoning", "")])),
                        is_system_generated=True
                    )
                    db.add(relation)
                    saved_count += 1

        db.commit()
        return saved_count
