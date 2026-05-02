"""
语义分析服务 - 结合向量检索和地理分析的串案分析
"""
from sqlalchemy.orm import Session
from app.models.case import Case
from app.services.vector_db_service import VectorDBService
from app.services.geo_analysis_service import GeoAnalysisService
from app.utils.geo import haversine_km
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from app.utils.logger import logger


class SemanticAnalysisService:
    """语义分析服务 - 结合向量检索和传统分析"""
    
    def __init__(self):
        self.vector_db = VectorDBService()
        self.geo_service = GeoAnalysisService
    
    def analyze_hybrid_serial_cases(
        self,
        db: Session,
        case_ids: Optional[List[int]] = None,
        max_distance_km: float = 2.0,
        time_window_days: int = 30,
        min_semantic_similarity: float = 0.6,
        use_semantic: bool = True,
        use_geo: bool = True
    ) -> List[Dict]:
        """
        混合分析串案：结合语义相似度和地理距离
        
        Args:
            db: 数据库会话
            case_ids: 可选的案件ID列表，如果为None则分析所有案件
            max_distance_km: 最大地理距离（公里）
            time_window_days: 时间窗口（天）
            min_semantic_similarity: 最小语义相似度阈值
            use_semantic: 是否使用语义分析
            use_geo: 是否使用地理分析
            
        Returns:
            串案组列表
        """
        if case_ids:
            cases = db.query(Case).filter(Case.id.in_(case_ids)).all()
        else:
            cases = db.query(Case).filter(
                Case.description.isnot(None),
                Case.description != ""
            ).all()
        
        if len(cases) < 2:
            return []
        
        # 按时间排序（统一去除时区信息避免比较异常）
        def strip_tz(dt):
            if dt is None:
                from datetime import datetime
                return datetime.min
            return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt

        cases_sorted = sorted(cases, key=lambda c: strip_tz(c.occurred_time))
        
        serial_groups = []
        processed = set()
        
        for i, case1 in enumerate(cases_sorted):
            if case1.id in processed:
                continue
            
            group = [case1]
            processed.add(case1.id)
            
            # 语义相似案件
            semantic_matches = []
            if use_semantic and self.vector_db.is_available():
                semantic_matches = self.vector_db.find_semantic_serial_cases(
                    case1.id,
                    top_k=20,
                    min_similarity=min_semantic_similarity
                )
            
            for case2 in cases_sorted[i+1:]:
                if case2.id in processed:
                    continue
                
                # 检查是否应该加入串案组
                should_include = False
                match_reasons = []
                
                # 语义相似度检查
                if use_semantic:
                    semantic_match = next(
                        (m for m in semantic_matches if m["case_id"] == case2.id),
                        None
                    )
                    if semantic_match:
                        should_include = True
                        match_reasons.append(f"语义相似度: {semantic_match['similarity']:.2%}")
                
                # 地理距离检查
                if use_geo and case1.latitude and case1.longitude and case2.latitude and case2.longitude:
                    dist_km = haversine_km(
                        case1.latitude, case1.longitude,
                        case2.latitude, case2.longitude
                    )
                    if dist_km <= max_distance_km:
                        should_include = True
                        match_reasons.append(f"地理距离: {dist_km:.2f}km")
                
                # 时间窗口检查（统一去除时区）
                t1 = strip_tz(case1.occurred_time)
                t2 = strip_tz(case2.occurred_time)
                time_diff = abs((t2 - t1).total_seconds() / 86400)
                if time_diff > time_window_days:
                    should_include = False  # 时间超出窗口，不加入

                structured_reasons = self._structured_match_reasons(case1, case2)
                if structured_reasons:
                    should_include = True
                    match_reasons.extend(structured_reasons)
                
                # 至少满足一个条件（语义或地理）且时间在窗口内
                if should_include and time_diff <= time_window_days:
                    group.append(case2)
                    processed.add(case2.id)
            
            if len(group) >= 2:
                # 计算组内特征
                avg_lat = sum(c.latitude for c in group if c.latitude) / len([c for c in group if c.latitude]) if any(c.latitude for c in group) else None
                avg_lng = sum(c.longitude for c in group if c.longitude) / len([c for c in group if c.longitude]) if any(c.longitude for c in group) else None
                
                # 分析共同特征
                case_types = [c.case_type for c in group if c.case_type]
                common_type = max(set(case_types), key=case_types.count) if case_types else None
                
                modus_operandi_list = [c.modus_operandi for c in group if c.modus_operandi]
                common_modus = max(set(modus_operandi_list), key=modus_operandi_list.count) if modus_operandi_list else None
                source_types = [c.source_type for c in group if c.source_type]
                common_source_type = max(set(source_types), key=source_types.count) if source_types else None
                oil_natures = [c.oil_nature for c in group if c.oil_nature]
                common_oil_nature = max(set(oil_natures), key=oil_natures.count) if oil_natures else None
                quality_scores = [
                    c.quality_score
                    for c in group
                    if isinstance(c.quality_score, (int, float))
                ]
                
                # 判断串案可能性
                has_semantic_match = use_semantic and any(
                    self.vector_db.find_semantic_serial_cases(c.id, top_k=5, min_similarity=min_semantic_similarity)
                    for c in group
                )
                has_geo_cluster = use_geo and avg_lat and avg_lng
                
                likely_serial = (
                    len(group) >= 3 or
                    (has_semantic_match and has_geo_cluster) or
                    (has_semantic_match and len(group) >= 2)
                )
                
                serial_groups.append({
                    "group_id": len(serial_groups) + 1,
                    "case_count": len(group),
                    "center_latitude": avg_lat,
                    "center_longitude": avg_lng,
                    "time_span_days": (
                        strip_tz(group[-1].occurred_time) - strip_tz(group[0].occurred_time)
                    ).days if len(group) > 1 else 0,
                    "common_case_type": common_type,
                    "common_modus_operandi": common_modus,
                    "common_source_type": common_source_type,
                    "common_oil_nature": common_oil_nature,
                    "average_quality_score": round(sum(quality_scores) / len(quality_scores), 2) if quality_scores else None,
                    "cases": [
                        {
                            "id": c.id,
                            "case_number": c.case_number,
                            "occurred_time": str(c.occurred_time),
                            "location": c.location,
                            "latitude": c.latitude,
                            "longitude": c.longitude,
                            "case_type": c.case_type,
                            "modus_operandi": c.modus_operandi,
                            "source_type": c.source_type,
                            "oil_nature": c.oil_nature,
                            "quality_score": c.quality_score,
                            "quality_level": c.quality_level,
                        }
                        for c in group
                    ],
                    "analysis": {
                        "likely_serial": likely_serial,
                        "has_semantic_match": has_semantic_match,
                        "has_geo_cluster": has_geo_cluster,
                        "match_type": "hybrid" if (has_semantic_match and has_geo_cluster) else ("semantic" if has_semantic_match else "geo"),
                        "suggestions": self._generate_suggestions(group, has_semantic_match, has_geo_cluster)
                    }
                })
        
        return serial_groups

    def _structured_match_reasons(self, case1: Case, case2: Case) -> List[str]:
        """基于新案件台账字段补充串案锚点，不依赖向量数据库。"""
        reasons: List[str] = []

        def _persons(case: Case) -> set:
            names = set()
            for p in case.involved_persons or []:
                if isinstance(p, dict) and p.get("name"):
                    names.add(p["name"])
            try:
                for p in case.persons or []:
                    if p.name:
                        names.add(p.name)
            except Exception:
                pass
            return names

        def _plates(case: Case) -> set:
            plates = set()
            vehicle_info = case.vehicle_info
            if isinstance(vehicle_info, dict) and vehicle_info.get("plate_number"):
                plates.add(vehicle_info["plate_number"])
            if isinstance(vehicle_info, list):
                for item in vehicle_info:
                    if isinstance(item, dict) and item.get("plate_number"):
                        plates.add(item["plate_number"])
            try:
                for vehicle in case.vehicles or []:
                    if vehicle.plate_number:
                        plates.add(vehicle.plate_number)
            except Exception:
                pass
            return plates

        duplicate_reasons = []
        common_persons = _persons(case1) & _persons(case2)
        common_plates = _plates(case1) & _plates(case2)
        if common_persons:
            duplicate_reasons.append(f"相同人员需核验: {', '.join(sorted(common_persons)[:3])}")
        if common_plates:
            duplicate_reasons.append(f"相同车辆需核验: {', '.join(sorted(common_plates)[:3])}")

        same_source = case1.source_type and case1.source_type == case2.source_type
        same_oil_nature = case1.oil_nature and case1.oil_nature == case2.oil_nature
        same_modus = case1.modus_operandi and case1.modus_operandi == case2.modus_operandi
        if same_source and same_oil_nature and same_modus:
            reasons.append(f"线索来源/原油性质/手法一致: {case1.source_type}/{case1.oil_nature}")
        elif case1.source_type and case1.source_type == case2.source_type:
            reasons.append(f"线索来源一致: {case1.source_type}")
        elif case1.oil_nature and case1.oil_nature == case2.oil_nature:
            reasons.append(f"原油性质一致: {case1.oil_nature}")
        if duplicate_reasons:
            reasons.extend(duplicate_reasons)
        return reasons
    
    def _generate_suggestions(
        self,
        group: List[Case],
        has_semantic_match: bool,
        has_geo_cluster: bool
    ) -> List[str]:
        """生成分析建议"""
        suggestions = []
        
        if has_semantic_match and has_geo_cluster:
            suggestions.append("相似条件高度集中：作案手法相似且地理位置接近")
            suggestions.append("建议复盘现场薄弱点、时间窗口和周边道路条件")
        elif has_semantic_match:
            suggestions.append("语义相似度高：作案手法或特征描述高度相似")
            suggestions.append("建议深入分析作案条件和现场防护短板")
        elif has_geo_cluster:
            suggestions.append("地理位置接近：可能存在地域性犯罪模式")
            suggestions.append("建议围绕该区域形成防控参考方案")
        
        if len(group) >= 3:
            suggestions.append("案件数量较多，建议沉淀为区域复盘专题")
        
        return suggestions
    
    def search_by_semantic_similarity(
        self,
        db: Session,
        query_text: str,
        top_k: int = 10,
        min_similarity: float = 0.5
    ) -> List[Dict]:
        """
        基于语义相似度搜索案件
        
        Args:
            db: 数据库会话
            query_text: 查询文本（如"打孔盗油"、"加油站盗窃"等）
            top_k: 返回最相似的k个案件
            min_similarity: 最小相似度阈值
            
        Returns:
            相似案件列表，包含完整案件信息
        """
        if not self.vector_db.is_available():
            logger.warning("向量数据库不可用，无法进行语义搜索")
            return []
        
        # 语义搜索
        similar_cases = self.vector_db.search_similar_cases(
            query_text,
            top_k=top_k,
            min_similarity=min_similarity
        )
        
        # 从数据库获取完整案件信息
        results = []
        for item in similar_cases:
            case = db.query(Case).filter(Case.id == item["case_id"]).first()
            if case:
                results.append({
                    "case": {
                        "id": case.id,
                        "case_number": case.case_number,
                        "occurred_time": str(case.occurred_time),
                        "location": case.location,
                        "latitude": case.latitude,
                        "longitude": case.longitude,
                        "case_type": case.case_type,
                        "description": case.description,
                        "modus_operandi": case.modus_operandi,
                    },
                    "similarity": item["similarity"],
                    "match_reason": "语义相似"
                })
        
        return results
