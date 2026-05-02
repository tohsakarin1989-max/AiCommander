from sqlalchemy.orm import Session
from app.models.case import Case
from app.utils.geo import haversine_km, bounding_box, create_grid_key, km_to_deg
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
from datetime import datetime, timedelta
import calendar

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
        db: Optional[Session] = None,
        radius_km: float = 0.5,
        min_cases: int = 3,
        cases: Optional[List[Case]] = None,
    ) -> List[Dict]:
        """
        识别案件热点区域（优化版：使用网格预分区减少 O(n²) 计算）

        Args:
            db: 数据库会话（可选，若提供 cases 则忽略）
            radius_km: 搜索半径（公里）
            min_cases: 热点最少案件数
            cases: 案件列表（可选，直接提供则跳过数据库查询）

        Returns:
            热点列表：包含中心坐标、案件数量、案件列表
        """
        if cases is None:
            if db is None:
                raise ValueError("必须提供 db 或 cases 参数")
            cases = GeoAnalysisService.get_all_cases_with_geo(db)
        if radius_km <= 0 or min_cases <= 0:
            return []
        if len(cases) < min_cases:
            return []

        # 使用网格预分区：将案件按网格分组，只需计算相邻网格内案件的距离
        # 网格大小略大于 radius_km，确保相邻网格覆盖搜索范围
        grid_size_deg = km_to_deg(radius_km) * 1.5

        # 构建网格索引
        grid_index: Dict[Tuple[int, int], List[Case]] = defaultdict(list)
        for case in cases:
            grid_key = create_grid_key(case.latitude, case.longitude, grid_size_deg)
            grid_index[grid_key].append(case)

        hotspots = []
        processed = set()

        for case in cases:
            if case.id in processed:
                continue

            # 只搜索当前网格及相邻 8 个网格（共 9 个）
            grid_x, grid_y = create_grid_key(case.latitude, case.longitude, grid_size_deg)

            nearby = []
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    for other in grid_index.get((grid_x + dx, grid_y + dy), []):
                        if other.id == case.id or other.id in processed:
                            continue
                        dist = haversine_km(
                            case.latitude, case.longitude,
                            other.latitude, other.longitude
                        )
                        if dist <= radius_km:
                            nearby.append(other)

            if len(nearby) + 1 >= min_cases:  # 包括中心案件
                # 标记所有聚类内案件为已处理
                for c in nearby:
                    processed.add(c.id)
                processed.add(case.id)

                # 计算热点中心
                all_cases_in_cluster = [case] + nearby
                avg_lat = sum(c.latitude for c in all_cases_in_cluster) / len(all_cases_in_cluster)
                avg_lng = sum(c.longitude for c in all_cases_in_cluster) / len(all_cases_in_cluster)
                source_distribution = defaultdict(int)
                oil_nature_distribution = defaultdict(int)
                quality_scores = []
                for c in all_cases_in_cluster:
                    source_distribution[c.source_type or "未标注"] += 1
                    if c.oil_nature:
                        oil_nature_distribution[c.oil_nature] += 1
                    if isinstance(c.quality_score, (int, float)):
                        quality_scores.append(c.quality_score)
                low_quality_count = sum(1 for score in quality_scores if score < 60)

                hotspots.append({
                    "center_latitude": avg_lat,
                    "center_longitude": avg_lng,
                    "case_count": len(all_cases_in_cluster),
                    "radius_km": radius_km,
                    "case_ids": [c.id for c in all_cases_in_cluster],
                    "source_distribution": dict(source_distribution),
                    "oil_nature_distribution": dict(oil_nature_distribution),
                    "average_quality_score": round(sum(quality_scores) / len(quality_scores), 2) if quality_scores else None,
                    "low_quality_count": low_quality_count,
                    "risk_score": min(
                        100,
                        len(all_cases_in_cluster) * 15
                        + low_quality_count * 3
                        + sum(1 for c in all_cases_in_cluster if c.oil_type or c.oil_nature) * 2,
                    ),
                    "cases": [
                        {
                            "id": c.id,
                            "case_number": c.case_number,
                            "occurred_time": str(c.occurred_time),
                            "location": c.location,
                            "latitude": c.latitude,
                            "longitude": c.longitude,
                            "case_type": c.case_type,
                            "source_type": c.source_type,
                            "oil_nature": c.oil_nature,
                            "quality_score": c.quality_score,
                            "quality_level": c.quality_level,
                        }
                        for c in all_cases_in_cluster
                    ]
                })

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
        
        # 按时间排序（去除时区信息统一比较）
        def _strip_tz(dt):
            if dt is None:
                from datetime import datetime
                return datetime.min
            return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt

        cases_sorted = sorted(cases, key=lambda c: _strip_tz(c.occurred_time))
        
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
                time_diff = abs((_strip_tz(case2.occurred_time) - _strip_tz(case1.occurred_time)).total_seconds() / 86400)
                
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
                    "time_span_days": (_strip_tz(group[-1].occurred_time) - _strip_tz(group[0].occurred_time)).days,
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
                            "复盘该区域道路、井场和技防薄弱条件",
                            "形成该区域防控参考"
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
                    "复盘相似案件条件",
                    "分析时间、空间、现场薄弱点等共同特征",
                    "沉淀区域防控经验"
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

    @staticmethod
    def find_hotspots_by_period(
        db: Session,
        months: int = 6,
        radius_km: float = 1.0,
        min_cases: int = 2,
    ) -> Dict:
        """
        按月份分段计算热点，返回热点时间演化数据

        Args:
            db: 数据库会话
            months: 分析最近几个月（每月为一个时间段）
            radius_km: 热点识别半径（公里）
            min_cases: 热点最少案件数

        Returns:
            包含各月热点及趋势摘要的字典
        """
        now = datetime.now()
        # 计算各月的起止时间段
        periods_meta = []
        for i in range(months - 1, -1, -1):
            # 往前推 i 个月
            year = now.year
            month = now.month - i
            while month <= 0:
                month += 12
                year -= 1
            _, last_day = calendar.monthrange(year, month)
            start_dt = datetime(year, month, 1, 0, 0, 0)
            end_dt = datetime(year, month, last_day, 23, 59, 59)
            periods_meta.append({
                "period": f"{year:04d}-{month:02d}",
                "start_date": start_dt.isoformat(),
                "end_date": end_dt.isoformat(),
                "start_dt": start_dt,
                "end_dt": end_dt,
            })

        # 一次性查出所有带坐标的案件，避免多次数据库查询
        all_cases = db.query(Case).filter(
            Case.latitude.isnot(None),
            Case.longitude.isnot(None),
            Case.occurred_time.isnot(None),
        ).all()

        def _strip_tz(dt: Optional[datetime]) -> Optional[datetime]:
            if dt is None:
                return None
            return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt

        periods_result = []
        for meta in periods_meta:
            start_dt = meta["start_dt"]
            end_dt = meta["end_dt"]

            # 筛选该月案件
            filtered = [
                c for c in all_cases
                if start_dt <= (_strip_tz(c.occurred_time) or datetime.min) <= end_dt
            ]

            # 调用通用热点识别（传入 cases 跳过数据库查询）
            raw_hotspots = GeoAnalysisService.find_hotspots(
                cases=filtered,
                radius_km=radius_km,
                min_cases=min_cases,
            )

            # 为每个热点生成跨月追踪键
            hotspots_out = []
            for hs in raw_hotspots:
                lat = hs["center_latitude"]
                lng = hs["center_longitude"]
                hotspot_key = f"{round(lat, 2)}_{round(lng, 2)}"
                hotspots_out.append({
                    "center_latitude": lat,
                    "center_longitude": lng,
                    "case_count": hs["case_count"],
                    "radius_km": hs["radius_km"],
                    "hotspot_key": hotspot_key,
                    "source_distribution": hs.get("source_distribution", {}),
                    "oil_nature_distribution": hs.get("oil_nature_distribution", {}),
                    "average_quality_score": hs.get("average_quality_score"),
                    "low_quality_count": hs.get("low_quality_count", 0),
                    "risk_score": hs.get("risk_score"),
                })

            periods_result.append({
                "period": meta["period"],
                "start_date": meta["start_date"],
                "end_date": meta["end_date"],
                "hotspots": hotspots_out,
                "total_cases": len(filtered),
            })

        # 计算趋势摘要：比较最后两个月热点变化
        heating_up = 0
        cooling_down = 0
        stable = 0
        new_hotspots = 0

        if len(periods_result) >= 2:
            last_period = periods_result[-1]
            prev_period = periods_result[-2]

            # 构建上个月热点的 key -> case_count 映射
            prev_map: Dict[str, int] = {
                hs["hotspot_key"]: hs["case_count"]
                for hs in prev_period["hotspots"]
            }
            prev_keys = set(prev_map.keys())
            last_keys = set(hs["hotspot_key"] for hs in last_period["hotspots"])

            # 新出现热点：本月有但上月没有的
            new_hotspots = len(last_keys - prev_keys)

            for hs in last_period["hotspots"]:
                key = hs["hotspot_key"]
                if key not in prev_map:
                    continue  # 新热点已单独统计
                prev_count = prev_map[key]
                curr_count = hs["case_count"]
                if curr_count > prev_count:
                    heating_up += 1
                elif curr_count < prev_count:
                    cooling_down += 1
                else:
                    stable += 1

        return {
            "periods": periods_result,
            "trend_summary": {
                "heating_up": heating_up,
                "cooling_down": cooling_down,
                "stable": stable,
                "new_hotspots": new_hotspots,
            },
            "months_analyzed": months,
        }
