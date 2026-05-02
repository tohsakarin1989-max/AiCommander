from sqlalchemy.orm import Session
from app.models.case import Case
from app.services.geo_analysis_service import GeoAnalysisService
from app.utils.geo import haversine_km
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import json

class DeploymentService:
    """
    工作部署建议服务
    基于已破获案件数据，生成预防性的工作部署建议
    """
    
    @staticmethod
    def analyze_temporal_patterns(db: Session, days: int = 90) -> Dict:
        """
        分析时间模式
        识别案件高发时段、日期规律等
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        cases = db.query(Case).filter(
            Case.occurred_time >= cutoff_date
        ).all()
        
        if len(cases) < 3:
            return {
                "total_cases": len(cases),
                "message": "案件数量不足，无法进行时间模式分析"
            }
        
        # 按小时统计
        hour_counts = defaultdict(int)
        # 按星期统计
        weekday_counts = defaultdict(int)
        # 按日期统计（识别特定日期规律）
        date_patterns = defaultdict(int)
        
        for case in cases:
            occurred = case.occurred_time
            hour_counts[occurred.hour] += 1
            weekday_counts[occurred.weekday()] += 1
            date_patterns[occurred.day] += 1
        
        # 找出高发时段
        high_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        high_weekdays = sorted(weekday_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        
        weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        
        return {
            "total_cases": len(cases),
            "analysis_period_days": days,
            "high_risk_hours": [
                {
                    "hour": hour,
                    "hour_range": f"{hour:02d}:00-{hour+1:02d}:00",
                    "case_count": count,
                    "percentage": round(count / len(cases) * 100, 1)
                }
                for hour, count in high_hours
            ],
            "high_risk_weekdays": [
                {
                    "weekday": weekday,
                    "weekday_name": weekday_names[weekday],
                    "case_count": count,
                    "percentage": round(count / len(cases) * 100, 1)
                }
                for weekday, count in high_weekdays
            ],
            "insights": [
                f"过去{days}天共发生{len(cases)}起案件",
                f"高发时段：{', '.join([f'{h[0]:02d}:00-{h[0]+1:02d}:00' for h in high_hours])}",
                f"高发日期：{', '.join([weekday_names[w[0]] for w in high_weekdays])}",
            ],
            "recommendations": [
                f"建议在高发时段（{high_hours[0][0]:02d}:00-{(high_hours[0][0]+1):02d}:00）加强巡逻",
                f"建议在{weekday_names[high_weekdays[0][0]]}等重点日期增加警力部署",
                "建议建立动态巡逻机制，根据时间规律调整巡逻频次"
            ]
        }
    
    @staticmethod
    def analyze_target_patterns(db: Session) -> Dict:
        """
        分析目标模式
        识别高发目标类型、设施类型等
        """
        cases = db.query(Case).filter(
            Case.case_type.isnot(None)
        ).all()
        
        if len(cases) < 3:
            return {
                "total_cases": len(cases),
                "message": "案件数量不足，无法进行目标模式分析"
            }
        
        # 按案件类型统计
        case_type_counts = defaultdict(int)
        # 按设施类型统计（涉油案件）
        facility_type_counts = defaultdict(int)
        # 按作案手法统计
        modus_counts = defaultdict(int)
        
        for case in cases:
            if case.case_type:
                case_type_counts[case.case_type] += 1
            if case.facility_type:
                facility_type_counts[case.facility_type] += 1
            if case.modus_operandi:
                modus_counts[case.modus_operandi] += 1
        
        return {
            "total_cases": len(cases),
            "high_risk_case_types": [
                {
                    "type": case_type,
                    "count": count,
                    "percentage": round(count / len(cases) * 100, 1)
                }
                for case_type, count in sorted(case_type_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            ],
            "high_risk_facilities": [
                {
                    "facility_type": facility_type,
                    "count": count,
                    "percentage": round(count / len([c for c in cases if c.facility_type]) * 100, 1) if len([c for c in cases if c.facility_type]) > 0 else 0
                }
                for facility_type, count in sorted(facility_type_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            ],
            "common_modus_operandi": [
                {
                    "modus": modus,
                    "count": count
                }
                for modus, count in sorted(modus_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            ],
            "recommendations": [
                "建议对高发目标类型加强防护措施",
                "建议对高发设施类型进行安全评估和加固",
                "建议针对常见作案手法制定专项防控方案"
            ]
        }
    
    @staticmethod
    def generate_patrol_routes(db: Session, radius_km: float = 2.0) -> Dict:
        """
        生成优化巡逻路线
        基于案件热点区域，生成推荐巡逻路线
        """
        hotspots = GeoAnalysisService.find_hotspots(db, radius_km=radius_km, min_cases=2)
        
        if not hotspots:
            return {
                "message": "未识别出明显的案件热点，建议采用常规巡逻路线",
                "routes": []
            }
        
        # 根据热点生成巡逻路线
        routes = []
        for i, hotspot in enumerate(hotspots[:5]):  # 最多5条路线
            routes.append({
                "route_id": i + 1,
                "route_name": f"热点区域{i+1}巡逻路线",
                "center_latitude": hotspot["center_latitude"],
                "center_longitude": hotspot["center_longitude"],
                "case_count": hotspot["case_count"],
                "priority": "高" if hotspot["case_count"] >= 5 else "中",
                "recommended_patrol_times": [
                    "08:00-12:00",
                    "14:00-18:00",
                    "20:00-24:00"
                ],
                "coverage_radius_km": radius_km,
                "suggestions": [
                    f"该区域过去发生{hotspot['case_count']}起案件，建议重点巡逻",
                    f"建议在巡逻路线中覆盖该区域周边{radius_km}公里范围",
                    "建议建立固定巡逻点和流动巡逻相结合的方式"
                ]
            })
        
        return {
            "total_routes": len(routes),
            "routes": routes,
            "recommendations": [
                "建议优先部署高优先级巡逻路线",
                "建议根据案件时间规律调整巡逻时段",
                "建议建立巡逻记录和反馈机制"
            ]
        }
    
    @staticmethod
    def generate_resource_allocation(db: Session) -> Dict:
        """
        生成资源配置建议
        基于案件分布和模式，建议警力、设备等资源配置
        """
        # 获取热点区域
        hotspots = GeoAnalysisService.find_hotspots(db, radius_km=0.5, min_cases=3)
        # 获取时间模式
        temporal = DeploymentService.analyze_temporal_patterns(db, days=90)
        # 获取目标模式
        target = DeploymentService.analyze_target_patterns(db)
        
        # 计算资源需求
        high_priority_areas = len([h for h in hotspots if h["case_count"] >= 5])
        medium_priority_areas = len([h for h in hotspots if h["case_count"] >= 3 and h["case_count"] < 5])
        
        resource_suggestions = []
        
        if high_priority_areas > 0:
            resource_suggestions.append({
                "type": "固定执勤点",
                "count": high_priority_areas,
                "description": f"建议在{high_priority_areas}个高优先级热点区域设置固定执勤点",
                "priority": "高"
            })
        
        if medium_priority_areas > 0:
            resource_suggestions.append({
                "type": "流动巡逻组",
                "count": medium_priority_areas,
                "description": f"建议在{medium_priority_areas}个中优先级区域部署流动巡逻组",
                "priority": "中"
            })
        
        # 基于时间模式建议
        if temporal.get("high_risk_hours"):
            peak_hours = [h["hour"] for h in temporal["high_risk_hours"][:2]]
            resource_suggestions.append({
                "type": "时段增援",
                "count": len(peak_hours),
                "description": f"建议在高发时段（{', '.join([f'{h:02d}:00' for h in peak_hours])}）增加巡逻频次",
                "priority": "高"
            })
        
        # 基于目标模式建议
        if target.get("high_risk_facilities"):
            resource_suggestions.append({
                "type": "重点目标防护",
                "count": len(target["high_risk_facilities"]),
                "description": f"建议对{len(target['high_risk_facilities'])}类高发设施类型加强防护",
                "priority": "中"
            })
        
        return {
            "total_hotspots": len(hotspots),
            "high_priority_areas": high_priority_areas,
            "medium_priority_areas": medium_priority_areas,
            "resource_suggestions": resource_suggestions,
            "recommendations": [
                "建议建立分级响应机制，高优先级区域重点部署",
                "建议建立动态调整机制，根据案件趋势调整资源配置",
                "建议建立多部门协作机制，形成防控合力"
            ]
        }
    
    @staticmethod
    def generate_prevention_measures(db: Session) -> Dict:
        """
        生成预防措施建议
        基于案件特征，提出针对性的预防措施
        """
        cases = db.query(Case).all()
        
        if len(cases) < 3:
            return {
                "message": "案件数量不足，无法生成预防措施建议"
            }
        
        # 分析案件特征
        target_patterns = DeploymentService.analyze_target_patterns(db)
        temporal_patterns = DeploymentService.analyze_temporal_patterns(db)
        
        measures = []
        
        # 基于时间模式的预防措施
        if temporal_patterns.get("high_risk_hours"):
            measures.append({
                "category": "时间防控",
                "measures": [
                    "在高发时段增加巡逻频次和密度",
                    "建立重点时段值班制度",
                    "在高发时段启用视频监控重点巡查"
                ],
                "priority": "高"
            })
        
        # 基于目标模式的预防措施
        if target_patterns.get("high_risk_facilities"):
            measures.append({
                "category": "目标防护",
                "measures": [
                    "对高发设施类型进行安全评估",
                    "加强高发设施的物理防护（围栏、监控等）",
                    "建立设施安全等级管理制度"
                ],
                "priority": "高"
            })
        
        # 基于地理模式的预防措施
        hotspots = GeoAnalysisService.find_hotspots(db)
        if hotspots:
            measures.append({
                "category": "区域防控",
                "measures": [
                    "在热点区域设置固定执勤点或监控点",
                    "建立热点区域定期巡查制度",
                    "在热点区域周边设置警示标识"
                ],
                "priority": "高"
            })
        
        # 基于作案手法的预防措施
        if target_patterns.get("common_modus_operandi"):
            measures.append({
                "category": "手法防控",
                "measures": [
                    "针对常见作案手法制定专项防控方案",
                    "加强相关工具和设备的管控",
                    "建立作案手法预警机制"
                ],
                "priority": "中"
            })
        
        return {
            "total_measures": len(measures),
            "measures": measures,
            "implementation_priority": [
                "优先实施高优先级预防措施",
                "建立预防措施效果评估机制",
                "根据案件趋势动态调整预防措施"
            ]
        }
    
    @staticmethod
    def generate_deployment_report(db: Session, days: int = 90) -> Dict:
        """
        生成完整的工作部署建议报告
        整合所有分析结果，生成综合部署建议
        """
        temporal = DeploymentService.analyze_temporal_patterns(db, days)
        target = DeploymentService.analyze_target_patterns(db)
        routes = DeploymentService.generate_patrol_routes(db)
        resources = DeploymentService.generate_resource_allocation(db)
        prevention = DeploymentService.generate_prevention_measures(db)
        
        # 生成综合建议
        summary = {
            "analysis_period": f"过去{days}天",
            "key_findings": [],
            "priority_actions": []
        }
        
        if temporal.get("high_risk_hours"):
            summary["key_findings"].append(
                f"识别出{temporal['high_risk_hours'][0]['hour_range']}为案件高发时段"
            )
            summary["priority_actions"].append(
                f"在高发时段（{temporal['high_risk_hours'][0]['hour_range']}）加强巡逻部署"
            )
        
        if routes.get("routes"):
            summary["key_findings"].append(
                f"识别出{len(routes['routes'])}个需要重点巡逻的热点区域"
            )
            summary["priority_actions"].append(
                f"优先部署{len([r for r in routes['routes'] if r['priority'] == '高'])}条高优先级巡逻路线"
            )
        
        if resources.get("high_priority_areas", 0) > 0:
            summary["priority_actions"].append(
                f"在{resources['high_priority_areas']}个高优先级区域设置固定执勤点"
            )
        
        return {
            "summary": summary,
            "temporal_analysis": temporal,
            "target_analysis": target,
            "patrol_routes": routes,
            "resource_allocation": resources,
            "prevention_measures": prevention,
            "generated_at": datetime.now().isoformat()
        }

    @staticmethod
    def optimize_route_order(hotspots: List[Dict]) -> List[Dict]:
        """
        贪心最近邻 TSP：给定多个热点坐标，返回最优访问顺序

        hotspot 格式：{"center_latitude": float, "center_longitude": float, "case_count": int, ...}

        返回：同格式 hotspot 列表，每条记录增加：
          - "visit_order": int  访问序号（从 1 开始）
          - "est_distance_km": float  到下一个点的距离（最后一个点为 0.0）

        算法：
        1. 从案件数最多的热点出发
        2. 每次选择距当前位置最近的未访问热点
        3. 记录每段距离，累计总距离
        """
        if not hotspots:
            return []

        # 过滤掉缺少坐标的热点
        valid = [
            h for h in hotspots
            if h.get("center_latitude") is not None and h.get("center_longitude") is not None
        ]
        if not valid:
            return []

        # 从案件数最多的热点出发
        unvisited = list(range(len(valid)))
        start_idx = max(unvisited, key=lambda i: valid[i].get("case_count", 0))

        ordered_indices: List[int] = [start_idx]
        unvisited.remove(start_idx)

        # 贪心最近邻
        while unvisited:
            current = ordered_indices[-1]
            cur_lat = valid[current]["center_latitude"]
            cur_lon = valid[current]["center_longitude"]
            nearest = min(
                unvisited,
                key=lambda i: haversine_km(
                    cur_lat, cur_lon,
                    valid[i]["center_latitude"],
                    valid[i]["center_longitude"],
                )
            )
            ordered_indices.append(nearest)
            unvisited.remove(nearest)

        # 构建结果列表，附加 visit_order 和 est_distance_km
        result = []
        for order, idx in enumerate(ordered_indices):
            h = dict(valid[idx])  # 不修改原始对象
            h["visit_order"] = order + 1
            # 计算到下一个点的距离
            if order < len(ordered_indices) - 1:
                next_idx = ordered_indices[order + 1]
                dist = haversine_km(
                    valid[idx]["center_latitude"],
                    valid[idx]["center_longitude"],
                    valid[next_idx]["center_latitude"],
                    valid[next_idx]["center_longitude"],
                )
                h["est_distance_km"] = round(dist, 2)
            else:
                h["est_distance_km"] = 0.0
            result.append(h)

        return result

