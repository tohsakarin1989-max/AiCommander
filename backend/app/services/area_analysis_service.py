"""
区域研判服务
以村屯/区域为单位进行事件聚合分析、风险评估和研判建议生成
"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, desc

from app.models.event import Event, AreaProfile, EventRelation, EVENT_TYPES
from app.models.case import Case
from app.services.relation_analysis_service import RelationAnalysisService
from app.utils.geo import haversine_km, bounding_box


class AreaAnalysisService:
    """区域研判服务"""

    # 风险评估参数
    RISK_WEIGHTS = {
        "stash_found": 30,       # 发现囤油点，风险高
        "vehicle_caught": 20,   # 抓获盗油车
        "theft_case": 25,        # 盗油案件
        "pipeline_tap": 35,      # 管线打孔点
        "illegal_station": 30,   # 非法加油站
        "damage_found": 15,      # 设施损坏
        "equipment_found": 20,   # 发现作案工具
        "suspect_activity": 10,  # 可疑活动
    }

    @staticmethod
    def analyze_area(
        db: Session,
        area_name: str,
        radius_km: float = 5.0,
        time_range_days: int = 365
    ) -> Dict:
        """
        分析指定区域（村屯）的事件聚集情况

        Args:
            db: 数据库会话
            area_name: 区域/村屯名称
            radius_km: 关联范围（公里）
            time_range_days: 分析的时间范围（天）

        Returns:
            区域分析结果，包含事件列表、统计、关联、风险评估和建议
        """
        # 获取区域内所有事件
        time_start = datetime.now() - timedelta(days=time_range_days)

        events = db.query(Event).filter(
            Event.village_name == area_name,
            Event.occurred_time >= time_start
        ).order_by(desc(Event.occurred_time)).all()

        if not events:
            return {
                "area_name": area_name,
                "events": [],
                "events_count": 0,
                "analysis": None,
                "message": "该区域暂无事件记录"
            }

        # 按类型统计
        type_counts = defaultdict(int)
        for e in events:
            type_counts[e.event_type] += 1

        # 时间分析
        times = [e.occurred_time for e in events if e.occurred_time]
        first_event_time = min(times) if times else None
        last_event_time = max(times) if times else None
        time_span_days = (last_event_time - first_event_time).days if len(times) > 1 else 0

        # 构建事件时间线
        timeline = AreaAnalysisService._build_timeline(events)

        # 分析事件之间的关联
        relations = AreaAnalysisService._analyze_internal_relations(db, events)

        # 风险评估
        risk_assessment = AreaAnalysisService._assess_risk(
            events, type_counts, time_span_days, relations
        )

        # 生成研判建议
        suggestions = AreaAnalysisService._generate_area_suggestions(
            area_name, events, type_counts, relations, risk_assessment
        )

        # 巡逻建议
        patrol_suggestions = AreaAnalysisService._generate_patrol_suggestions(
            area_name, events, type_counts
        )

        return {
            "area_name": area_name,
            "events": events,
            "events_count": len(events),
            "type_counts": dict(type_counts),
            "timeline": timeline,
            "time_analysis": {
                "first_event": first_event_time,
                "last_event": last_event_time,
                "time_span_days": time_span_days,
                "is_active": (datetime.now() - last_event_time).days <= 90 if last_event_time else False
            },
            "relations": relations,
            "risk_assessment": risk_assessment,
            "suggestions": suggestions,
            "patrol_suggestions": patrol_suggestions
        }

    @staticmethod
    def analyze_area_by_coordinates(
        db: Session,
        center_lat: float,
        center_lng: float,
        radius_km: float = 5.0,
        time_range_days: int = 365
    ) -> Dict:
        """
        基于坐标分析指定范围内的事件

        适用于没有明确村屯名称的情况
        """
        time_start = datetime.now() - timedelta(days=time_range_days)

        # 使用边界框预筛选
        min_lat, max_lat, min_lng, max_lng = bounding_box(center_lat, center_lng, radius_km)

        events = db.query(Event).filter(
            Event.latitude.between(min_lat, max_lat),
            Event.longitude.between(min_lng, max_lng),
            Event.occurred_time >= time_start
        ).all()

        # 精确距离过滤
        filtered_events = []
        for e in events:
            if e.latitude and e.longitude:
                dist = haversine_km(center_lat, center_lng, e.latitude, e.longitude)
                if dist <= radius_km:
                    filtered_events.append(e)

        if not filtered_events:
            return {
                "center": {"latitude": center_lat, "longitude": center_lng},
                "radius_km": radius_km,
                "events": [],
                "events_count": 0,
                "message": "该范围内暂无事件记录"
            }

        # 复用区域分析逻辑
        type_counts = defaultdict(int)
        for e in filtered_events:
            type_counts[e.event_type] += 1

        times = [e.occurred_time for e in filtered_events if e.occurred_time]
        first_event_time = min(times) if times else None
        last_event_time = max(times) if times else None
        time_span_days = (last_event_time - first_event_time).days if len(times) > 1 else 0

        timeline = AreaAnalysisService._build_timeline(filtered_events)
        relations = AreaAnalysisService._analyze_internal_relations(db, filtered_events)
        risk_assessment = AreaAnalysisService._assess_risk(
            filtered_events, type_counts, time_span_days, relations
        )

        # 识别涉及的村屯
        villages = set(e.village_name for e in filtered_events if e.village_name)

        return {
            "center": {"latitude": center_lat, "longitude": center_lng},
            "radius_km": radius_km,
            "involved_villages": list(villages),
            "events": filtered_events,
            "events_count": len(filtered_events),
            "type_counts": dict(type_counts),
            "timeline": timeline,
            "time_analysis": {
                "first_event": first_event_time,
                "last_event": last_event_time,
                "time_span_days": time_span_days
            },
            "relations": relations,
            "risk_assessment": risk_assessment
        }

    @staticmethod
    def get_high_risk_areas(db: Session, limit: int = 10) -> List[Dict]:
        """
        获取高风险区域列表

        Returns:
            按风险等级排序的区域列表
        """
        # 获取所有有事件的村屯
        village_stats = db.query(
            Event.village_name,
            func.count(Event.id).label('event_count'),
            func.max(Event.occurred_time).label('last_event')
        ).filter(
            Event.village_name.isnot(None)
        ).group_by(Event.village_name).all()

        risk_areas = []
        for village_name, event_count, last_event in village_stats:
            if not village_name:
                continue

            # 获取该村屯的事件类型统计
            type_stats = db.query(
                Event.event_type,
                func.count(Event.id)
            ).filter(
                Event.village_name == village_name
            ).group_by(Event.event_type).all()

            type_counts = {t: c for t, c in type_stats}

            # 计算风险分数
            risk_score = 0
            for event_type, count in type_counts.items():
                weight = AreaAnalysisService.RISK_WEIGHTS.get(event_type, 5)
                risk_score += weight * count

            # 近期活跃加权
            if last_event:
                days_since = (datetime.now() - last_event).days
                if days_since <= 30:
                    risk_score *= 1.5
                elif days_since <= 90:
                    risk_score *= 1.2

            # 确定风险等级
            if risk_score >= 100:
                risk_level = "critical"
            elif risk_score >= 60:
                risk_level = "high"
            elif risk_score >= 30:
                risk_level = "medium"
            else:
                risk_level = "low"

            risk_areas.append({
                "area_name": village_name,
                "event_count": event_count,
                "last_event": last_event,
                "type_counts": type_counts,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "days_since_last": (datetime.now() - last_event).days if last_event else None
            })

        # 按风险分数排序
        risk_areas.sort(key=lambda x: -x["risk_score"])
        return risk_areas[:limit]

    @staticmethod
    def get_area_risk_ranking(db: Session, limit: int = 10) -> List[Dict]:
        """兼容 API 层使用的区域风险排名入口。"""
        return AreaAnalysisService.get_high_risk_areas(db, limit=limit)

    @staticmethod
    def identify_hotspots(
        db: Session,
        days_back: int = 90,
        min_events: int = 2
    ) -> List[Dict]:
        """
        识别近期事件热点区域。

        以 village_name 为聚合单元，返回达到最小事件数阈值的区域。
        """
        if days_back <= 0 or min_events <= 0:
            return []

        cutoff = datetime.now() - timedelta(days=days_back)
        village_stats = db.query(
            Event.village_name,
            func.count(Event.id).label("event_count"),
            func.max(Event.occurred_time).label("last_event"),
            func.avg(Event.latitude).label("center_latitude"),
            func.avg(Event.longitude).label("center_longitude"),
        ).filter(
            Event.village_name.isnot(None),
            Event.occurred_time >= cutoff,
        ).group_by(Event.village_name).having(
            func.count(Event.id) >= min_events
        ).all()

        hotspots = []
        for village_name, event_count, last_event, center_latitude, center_longitude in village_stats:
            type_stats = db.query(
                Event.event_type,
                func.count(Event.id),
            ).filter(
                Event.village_name == village_name,
                Event.occurred_time >= cutoff,
            ).group_by(Event.event_type).all()
            type_counts = {event_type: count for event_type, count in type_stats}

            risk_score = 0
            for event_type, count in type_counts.items():
                risk_score += AreaAnalysisService.RISK_WEIGHTS.get(event_type, 5) * count

            if last_event:
                comparable_last_event = (
                    last_event.replace(tzinfo=None)
                    if last_event.tzinfo is not None else last_event
                )
                days_since_last = (datetime.now() - comparable_last_event).days
                if days_since_last <= 30:
                    risk_score *= 1.5
                elif days_since_last <= 90:
                    risk_score *= 1.2
            else:
                days_since_last = None

            if risk_score >= 100:
                risk_level = "critical"
            elif risk_score >= 60:
                risk_level = "high"
            elif risk_score >= 30:
                risk_level = "medium"
            else:
                risk_level = "low"

            hotspots.append({
                "area_name": village_name,
                "event_count": event_count,
                "last_event": last_event,
                "center_latitude": center_latitude,
                "center_longitude": center_longitude,
                "type_counts": type_counts,
                "risk_score": round(risk_score, 1),
                "risk_level": risk_level,
                "days_since_last": days_since_last,
            })

        hotspots.sort(key=lambda item: (-item["event_count"], -item["risk_score"]))
        return hotspots

    @staticmethod
    def update_area_profile(db: Session, area_name: str) -> AreaProfile:
        """
        更新或创建区域档案

        基于最新事件数据更新统计信息和风险评估
        """
        # 获取或创建区域档案
        profile = db.query(AreaProfile).filter(
            AreaProfile.area_name == area_name
        ).first()

        if not profile:
            profile = AreaProfile(area_name=area_name)
            db.add(profile)

        # 获取该区域所有事件
        events = db.query(Event).filter(
            Event.village_name == area_name
        ).all()

        if events:
            # 计算中心点
            lats = [e.latitude for e in events if e.latitude]
            lngs = [e.longitude for e in events if e.longitude]
            if lats and lngs:
                profile.center_latitude = sum(lats) / len(lats)
                profile.center_longitude = sum(lngs) / len(lngs)

            # 统计数据
            profile.total_events = len(events)

            now = datetime.now()
            profile.events_last_30_days = len([
                e for e in events
                if e.occurred_time and (now - e.occurred_time).days <= 30
            ])
            profile.events_last_90_days = len([
                e for e in events
                if e.occurred_time and (now - e.occurred_time).days <= 90
            ])

            times = [e.occurred_time for e in events if e.occurred_time]
            if times:
                profile.first_event_time = min(times)
                profile.last_event_time = max(times)

            # 类型统计
            type_counts = defaultdict(int)
            for e in events:
                type_counts[e.event_type] += 1
            profile.event_types_count = dict(type_counts)

            # 风险评估
            risk_assessment = AreaAnalysisService._assess_risk(
                events, type_counts,
                (profile.last_event_time - profile.first_event_time).days if len(times) > 1 else 0,
                []
            )
            profile.risk_level = risk_assessment["level"]
            profile.risk_score = risk_assessment["score"]
            profile.risk_factors = risk_assessment["factors"]
            profile.risk_updated_at = now

            # 生成建议
            suggestions = AreaAnalysisService._generate_area_suggestions(
                area_name, events, type_counts, [], risk_assessment
            )
            profile.suggested_actions = suggestions

            patrol_suggestions = AreaAnalysisService._generate_patrol_suggestions(
                area_name, events, type_counts
            )
            profile.patrol_suggestions = patrol_suggestions

        db.commit()
        return profile

    @staticmethod
    def _build_timeline(events: List[Event]) -> List[Dict]:
        """构建事件时间线"""
        timeline = []
        sorted_events = sorted(events, key=lambda e: e.occurred_time or datetime.min)

        for e in sorted_events:
            timeline.append({
                "id": e.id,
                "event_number": e.event_number,
                "event_type": e.event_type,
                "event_type_name": EVENT_TYPES.get(e.event_type, e.event_type),
                "occurred_time": e.occurred_time,
                "title": e.title or e.description[:50] if e.description else None,
                "location": e.location,
                "handling_result": e.handling_result
            })

        return timeline

    @staticmethod
    def _analyze_internal_relations(db: Session, events: List[Event]) -> List[Dict]:
        """分析区域内事件之间的关联"""
        relations = []
        event_ids = {e.id for e in events}

        for i, e1 in enumerate(events):
            for e2 in events[i + 1:]:
                # 检查空间关联
                if e1.latitude and e1.longitude and e2.latitude and e2.longitude:
                    distance = haversine_km(
                        e1.latitude, e1.longitude,
                        e2.latitude, e2.longitude
                    )
                    if distance <= 5:  # 5km内
                        relation = {
                            "event_a_id": e1.id,
                            "event_b_id": e2.id,
                            "event_a_type": e1.event_type,
                            "event_b_type": e2.event_type,
                            "distance_km": round(distance, 2),
                            "time_gap_days": abs((e1.occurred_time - e2.occurred_time).days) if e1.occurred_time and e2.occurred_time else None,
                            "relation_types": ["spatial_cluster"]
                        }

                        # 检查上下游关联
                        if AreaAnalysisService._is_supply_chain_pair(e1.event_type, e2.event_type):
                            relation["relation_types"].append("supply_chain")
                            relation["supply_chain_note"] = AreaAnalysisService._get_supply_chain_note(
                                e1.event_type, e2.event_type
                            )

                        relations.append(relation)

        return relations

    @staticmethod
    def _is_supply_chain_pair(type_a: str, type_b: str) -> bool:
        """判断两个事件类型是否可能是上下游关系"""
        supply_chain_pairs = [
            ("pipeline_tap", "stash_found"),
            ("pipeline_tap", "vehicle_caught"),
            ("theft_case", "stash_found"),
            ("theft_case", "vehicle_caught"),
            ("vehicle_caught", "stash_found"),
            ("stash_found", "illegal_station"),
        ]
        return (type_a, type_b) in supply_chain_pairs or (type_b, type_a) in supply_chain_pairs

    @staticmethod
    def _get_supply_chain_note(type_a: str, type_b: str) -> str:
        """获取上下游关联说明"""
        notes = {
            ("pipeline_tap", "stash_found"): "打孔点可能是囤油点的油源",
            ("theft_case", "stash_found"): "盗油案件与囤油点可能属于同一链条",
            ("vehicle_caught", "stash_found"): "盗油车可能与囤油点有关联",
            ("pipeline_tap", "vehicle_caught"): "打孔点与抓获车辆可能是作案现场与运输环节",
        }
        return notes.get((type_a, type_b), notes.get((type_b, type_a), "可能存在上下游关联"))

    @staticmethod
    def _assess_risk(
        events: List[Event],
        type_counts: Dict[str, int],
        time_span_days: int,
        relations: List[Dict]
    ) -> Dict:
        """评估区域风险"""
        risk_score = 0
        risk_factors = []

        # 1. 基于事件类型计算基础风险分
        for event_type, count in type_counts.items():
            weight = AreaAnalysisService.RISK_WEIGHTS.get(event_type, 5)
            risk_score += weight * count

            if event_type == "stash_found" and count >= 1:
                risk_factors.append(f"发现{count}处囤油点")
            elif event_type == "pipeline_tap" and count >= 1:
                risk_factors.append(f"发现{count}处管线打孔点")
            elif event_type == "vehicle_caught" and count >= 2:
                risk_factors.append(f"多次抓获盗油车辆（{count}次）")

        # 2. 事件数量加权
        if len(events) >= 5:
            risk_score *= 1.3
            risk_factors.append(f"事件数量较多（{len(events)}起）")
        elif len(events) >= 3:
            risk_score *= 1.1

        # 3. 时间持续性加权
        if time_span_days >= 180:
            risk_score *= 1.2
            risk_factors.append(f"活动持续时间长（{time_span_days}天）")
        elif time_span_days >= 90:
            risk_score *= 1.1

        # 4. 存在上下游关联
        supply_chain_relations = [r for r in relations if "supply_chain" in r.get("relation_types", [])]
        if supply_chain_relations:
            risk_score *= 1.3
            risk_factors.append("存在上下游关联，可能是完整盗油链条")

        # 5. 近期活跃度
        recent_events = [e for e in events if e.occurred_time and (datetime.now() - e.occurred_time).days <= 30]
        if recent_events:
            risk_score *= 1.2
            risk_factors.append(f"近30天仍有活动（{len(recent_events)}起）")

        # 确定风险等级
        if risk_score >= 100:
            risk_level = "critical"
        elif risk_score >= 60:
            risk_level = "high"
        elif risk_score >= 30:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "level": risk_level,
            "score": round(risk_score, 1),
            "factors": risk_factors
        }

    @staticmethod
    def _generate_area_suggestions(
        area_name: str,
        events: List[Event],
        type_counts: Dict[str, int],
        relations: List[Dict],
        risk_assessment: Dict
    ) -> List[Dict]:
        """生成区域研判建议"""
        suggestions = []

        # 1. 基于风险等级的总体建议
        if risk_assessment["level"] in ["critical", "high"]:
            suggestions.append({
                "type": "alert",
                "priority": "high",
                "title": "高风险区域预警",
                "content": f"{area_name}被评估为{risk_assessment['level']}风险区域",
                "action": "建议列为重点关注区域，加强巡逻力度"
            })

        # 2. 存在囤油点
        if type_counts.get("stash_found", 0) >= 1:
            suggestions.append({
                "type": "investigation",
                "priority": "high",
                "title": "排查其他囤油点",
                "content": f"已在该区域发现{type_counts['stash_found']}处囤油点",
                "action": "建议排查周边5公里范围内是否还有其他囤油点或窝点"
            })

        # 3. 多次抓获车辆
        if type_counts.get("vehicle_caught", 0) >= 2:
            suggestions.append({
                "type": "tracking",
                "priority": "high",
                "title": "车辆活动规律分析",
                "content": f"该区域多次抓获盗油车辆（{type_counts['vehicle_caught']}次）",
                "action": "分析车辆活动时间规律，在高发时段加强主要道路卡口检查"
            })

        # 4. 存在上下游关联
        supply_chain = [r for r in relations if "supply_chain" in r.get("relation_types", [])]
        if supply_chain:
            suggestions.append({
                "type": "chain_analysis",
                "priority": "high",
                "title": "盗油链条分析",
                "content": "该区域事件存在上下游关联，可能是完整盗油链条的一部分",
                "action": "建议深入分析油源→运输→囤积→销赃各环节，寻找链条上的其他点位"
            })

        # 5. 团伙窝点排查
        if len(events) >= 3 and risk_assessment["level"] in ["critical", "high"]:
            suggestions.append({
                "type": "investigation",
                "priority": "medium",
                "title": "团伙窝点排查",
                "content": "多起事件聚集于该区域，可能存在盗油团伙窝点",
                "action": "建议关注该村屯内的可疑租住人员、改装车辆和异常存储设施"
            })

        return suggestions

    @staticmethod
    def _generate_patrol_suggestions(
        area_name: str,
        events: List[Event],
        type_counts: Dict[str, int]
    ) -> Dict:
        """生成巡逻建议"""
        # 分析时间规律
        hour_counts = defaultdict(int)
        weekday_counts = defaultdict(int)

        for e in events:
            if e.occurred_time:
                hour_counts[e.occurred_time.hour] += 1
                weekday_counts[e.occurred_time.weekday()] += 1

        # 找出高发时段
        peak_hours = sorted(hour_counts.items(), key=lambda x: -x[1])[:3]
        peak_weekdays = sorted(weekday_counts.items(), key=lambda x: -x[1])[:2]

        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

        # 关注目标
        watch_targets = []
        if type_counts.get("vehicle_caught", 0) > 0:
            # 收集涉案车辆特征
            vehicle_types = set()
            for e in events:
                if e.vehicles:
                    for v in e.vehicles:
                        if isinstance(v, dict) and v.get("type"):
                            vehicle_types.add(v["type"])
            if vehicle_types:
                watch_targets.append({
                    "type": "vehicle",
                    "description": f"重点关注车型：{', '.join(vehicle_types)}"
                })

        if type_counts.get("stash_found", 0) > 0:
            watch_targets.append({
                "type": "facility",
                "description": "关注废弃厂房、偏僻院落等可能的囤油场所"
            })

        if type_counts.get("pipeline_tap", 0) > 0:
            watch_targets.append({
                "type": "behavior",
                "description": "关注管线沿线异常停留的车辆和人员"
            })

        return {
            "area_name": area_name,
            "priority_level": "high" if len(events) >= 3 else "medium",
            "suggested_times": [
                {
                    "period": f"{h}:00-{(h+2)%24}:00",
                    "reason": f"历史事件高发时段（{c}起）"
                }
                for h, c in peak_hours if c >= 2
            ],
            "suggested_days": [
                {
                    "day": weekday_names[d],
                    "reason": f"历史事件较多（{c}起）"
                }
                for d, c in peak_weekdays if c >= 2
            ],
            "watch_targets": watch_targets,
            "patrol_points": [
                "村屯主要进出道路",
                "管线穿越点和阀门井",
                "偏僻的废弃建筑和院落"
            ]
        }
