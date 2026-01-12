from sqlalchemy.orm import Session
from app.models.case import Case
from app.utils.geo import haversine_km, bounding_box
from typing import List, Dict, Tuple
from collections import defaultdict
from datetime import datetime, timedelta
import math

class GeoAnalysisService:
    """地理线索分析服务 - 基于经纬度进行案件空间研判"""
    
    @staticmethod
    def get_all_cases_with_geo(db: Session) -> List[Case]:
        """获取所有带经纬度的案件"""
        return db.query(Case).filter(
            Case.latitude.isnot(None),
            Case.longitude.isnot(None)
        ).all()
    
    @staticmethod
    def find_hotspots(
        db: Session,
        radius_km: float = 0.5,
        min_cases: int = 3
    ) -> List[Dict]:
        """
        识别案件热点区域
        返回：热点中心坐标、案件数量、案件列表
        """
        cases = GeoAnalysisService.get_all_cases_with_geo(db)
        if len(cases) < min_cases:
            return []
        
        # 使用网格聚类方法识别热点
        hotspots = []
        processed = set()
        
        for case in cases:
            if case.id in processed:
                continue
            
            # 找到该案件附近的所有案件
            nearby = []
            for other in cases:
                if other.id == case.id:
                    continue
                dist = haversine_km(
                    case.latitude, case.longitude,
                    other.latitude, other.longitude
                )
                if dist <= radius_km:
                    nearby.append(other)
                    processed.add(other.id)
            
            if len(nearby) + 1 >= min_cases:  # 包括中心案件
                # 计算热点中心（所有案件的平均坐标）
                all_cases_in_cluster = [case] + nearby
                avg_lat = sum(c.latitude for c in all_cases_in_cluster) / len(all_cases_in_cluster)
                avg_lng = sum(c.longitude for c in all_cases_in_cluster) / len(all_cases_in_cluster)
                
                hotspots.append({
                    "center_latitude": avg_lat,
                    "center_longitude": avg_lng,
                    "case_count": len(all_cases_in_cluster),
                    "radius_km": radius_km,
                    "case_ids": [c.id for c in all_cases_in_cluster],
                    "cases": [
                        {
                            "id": c.id,
                            "case_number": c.case_number,
                            "occurred_time": str(c.occurred_time),
                            "location": c.location,
                            "latitude": c.latitude,
                            "longitude": c.longitude,
                            "case_type": c.case_type,
                        }
                        for c in all_cases_in_cluster
                    ]
                })
                processed.add(case.id)
        
        # 按案件数量排序
        hotspots.sort(key=lambda x: x["case_count"], reverse=True)
        return hotspots
    
    @staticmethod
    def analyze_serial_cases(
        db: Session,
        case_ids: List[int] = None,
        max_distance_km: float = 2.0,
        time_window_days: int = 30
    ) -> List[Dict]:
        """
        分析可能的串案（空间和时间上接近的案件）
        返回：串案组，包含案件列表和关联分析
        """
        if case_ids:
            cases = db.query(Case).filter(
                Case.id.in_(case_ids),
                Case.latitude.isnot(None),
                Case.longitude.isnot(None)
            ).all()
        else:
            cases = GeoAnalysisService.get_all_cases_with_geo(db)
        
        if len(cases) < 2:
            return []
        
        # 按时间排序
        cases_sorted = sorted(cases, key=lambda c: c.occurred_time)
        
        serial_groups = []
        processed = set()
        
        for i, case1 in enumerate(cases_sorted):
            if case1.id in processed:
                continue
            
            group = [case1]
            processed.add(case1.id)
            
            for case2 in cases_sorted[i+1:]:
                if case2.id in processed:
                    continue
                
                # 计算空间距离
                dist_km = haversine_km(
                    case1.latitude, case1.longitude,
                    case2.latitude, case2.longitude
                )
                
                # 计算时间间隔
                time_diff = abs((case2.occurred_time - case1.occurred_time).total_seconds() / 86400)
                
                # 如果空间和时间都接近，可能是串案
                if dist_km <= max_distance_km and time_diff <= time_window_days:
                    group.append(case2)
                    processed.add(case2.id)
            
            if len(group) >= 2:
                # 计算组内平均距离和特征
                avg_lat = sum(c.latitude for c in group) / len(group)
                avg_lng = sum(c.longitude for c in group) / len(group)
                
                # 分析共同特征
                case_types = [c.case_type for c in group if c.case_type]
                common_type = max(set(case_types), key=case_types.count) if case_types else None
                
                serial_groups.append({
                    "group_id": len(serial_groups) + 1,
                    "case_count": len(group),
                    "center_latitude": avg_lat,
                    "center_longitude": avg_lng,
                    "time_span_days": (group[-1].occurred_time - group[0].occurred_time).days,
                    "common_case_type": common_type,
                    "cases": [
                        {
                            "id": c.id,
                            "case_number": c.case_number,
                            "occurred_time": str(c.occurred_time),
                            "location": c.location,
                            "latitude": c.latitude,
                            "longitude": c.longitude,
                            "case_type": c.case_type,
                        }
                        for c in group
                    ],
                    "analysis": {
                        "likely_serial": len(group) >= 3,
                        "spatial_cluster": True,
                        "temporal_cluster": True,
                        "suggestions": [
                            "建议重点排查该区域",
                            "可能存在同一团伙作案",
                            "建议加强该区域巡逻"
                        ] if len(group) >= 3 else []
                    }
                })
        
        return serial_groups
    
    @staticmethod
    def analyze_geographic_patterns(
        db: Session,
        case_ids: List[int] = None
    ) -> Dict:
        """
        分析地理模式（分布特征、路径分析等）
        返回：地理分析报告
        """
        if case_ids:
            cases = db.query(Case).filter(
                Case.id.in_(case_ids),
                Case.latitude.isnot(None),
                Case.longitude.isnot(None)
            ).all()
        else:
            cases = GeoAnalysisService.get_all_cases_with_geo(db)
        
        if len(cases) < 2:
            return {
                "total_cases": len(cases),
                "message": "案件数量不足，无法进行地理模式分析"
            }
        
        # 计算地理边界
        lats = [c.latitude for c in cases]
        lngs = [c.longitude for c in cases]
        min_lat, max_lat = min(lats), max(lats)
        min_lng, max_lng = min(lngs), max(lngs)
        
        # 计算中心点
        center_lat = (min_lat + max_lat) / 2
        center_lng = (min_lng + max_lng) / 2
        
        # 计算分布范围（最大距离）
        max_dist = 0
        for i, c1 in enumerate(cases):
            for c2 in cases[i+1:]:
                dist = haversine_km(c1.latitude, c1.longitude, c2.latitude, c2.longitude)
                max_dist = max(max_dist, dist)
        
        # 按区域统计（简单网格划分）
        region_stats = defaultdict(int)
        for case in cases:
            # 简单网格：每0.1度一个格子
            grid_lat = int(case.latitude * 10)
            grid_lng = int(case.longitude * 10)
            region_stats[f"{grid_lat},{grid_lng}"] += 1
        
        top_regions = sorted(region_stats.items(), key=lambda x: x[1], reverse=True)[:5]
        
        return {
            "total_cases": len(cases),
            "geographic_bounds": {
                "min_latitude": min_lat,
                "max_latitude": max_lat,
                "min_longitude": min_lng,
                "max_longitude": max_lng,
                "center_latitude": center_lat,
                "center_longitude": center_lng,
                "span_km": max_dist
            },
            "distribution": {
                "max_distance_km": round(max_dist, 2),
                "density": len(cases) / (max_dist ** 2) if max_dist > 0 else 0,
                "top_regions": [
                    {"grid": k, "case_count": v}
                    for k, v in top_regions
                ]
            },
            "insights": [
                f"案件分布在 {round(max_dist, 2)} 公里范围内",
                f"中心位置：纬度 {center_lat:.6f}，经度 {center_lng:.6f}",
                f"共识别出 {len(top_regions)} 个高发区域"
            ]
        }
    
    @staticmethod
    def generate_geographic_clues(
        db: Session,
        case_ids: List[int] = None
    ) -> Dict:
        """
        生成地理线索研判报告
        综合热点、串案、地理模式等信息
        """
        hotspots = GeoAnalysisService.find_hotspots(db)
        serial_cases = GeoAnalysisService.analyze_serial_cases(db, case_ids)
        patterns = GeoAnalysisService.analyze_geographic_patterns(db, case_ids)
        
        clues = []
        
        # 热点区域线索
        if hotspots:
            clues.append({
                "type": "hotspot",
                "title": "案件热点区域",
                "description": f"识别出 {len(hotspots)} 个案件热点区域",
                "details": hotspots[:5],  # 只返回前5个
                "suggestions": [
                    "建议加强热点区域巡逻",
                    "重点关注热点区域周边设施安全",
                    "分析热点区域形成原因"
                ]
            })
        
        # 串案线索
        if serial_cases:
            likely_serials = [g for g in serial_cases if g["analysis"]["likely_serial"]]
            clues.append({
                "type": "serial",
                "title": "疑似串案分析",
                "description": f"识别出 {len(serial_cases)} 个串案组，其中 {len(likely_serials)} 个高度疑似",
                "details": serial_cases[:5],  # 只返回前5个
                "suggestions": [
                    "建议并案侦查",
                    "分析串案共同特征",
                    "排查是否存在同一团伙"
                ]
            })
        
        # 地理模式线索
        if patterns.get("total_cases", 0) > 0:
            clues.append({
                "type": "pattern",
                "title": "地理分布模式",
                "description": patterns.get("insights", []),
                "details": patterns,
                "suggestions": [
                    "分析案件分布规律",
                    "识别高风险区域",
                    "优化巡逻路线"
                ]
            })
        
        return {
            "summary": f"共识别 {len(clues)} 类地理线索",
            "clues": clues,
            "recommendations": [
                "结合地图可视化分析案件分布",
                "重点关注热点区域和串案组",
                "根据地理模式优化防控策略"
            ]
        }

