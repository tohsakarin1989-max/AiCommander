"""
轨迹路径条件复盘服务
基于已发生案件的时序位置数据，复盘距离、方向、时间差和周边条件。
"""
from sqlalchemy.orm import Session
from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset
from app.utils.geo import haversine_km, calculate_bearing
from typing import Any, List, Dict
from datetime import datetime
from collections import defaultdict
from app.utils.logger import logger
from app.ai.llm_providers import LLMProvider


class TrajectoryService:
    """已发生案件路径条件复盘服务。"""
    
    @staticmethod
    def extract_trajectory(
        db: Session,
        case_ids: List[int],
        time_order: bool = True
    ) -> List[Dict]:
        """
        提取案件轨迹（按时间顺序）
        
        Args:
            db: 数据库会话
            case_ids: 案件ID列表
            time_order: 是否按时间排序
            
        Returns:
            轨迹点列表，每个点包含时间、位置等信息
        """
        cases = db.query(Case).filter(
            Case.id.in_(case_ids),
            Case.latitude.isnot(None),
            Case.longitude.isnot(None)
        ).all()
        
        if not cases:
            return []
        
        if time_order:
            cases = sorted(cases, key=lambda c: c.occurred_time or datetime.min)
        
        trajectory = []
        for i, case in enumerate(cases):
            trajectory.append({
                "case_id": case.id,
                "case_number": case.case_number,
                "timestamp": case.occurred_time.isoformat() if case.occurred_time else None,
                "latitude": case.latitude,
                "longitude": case.longitude,
                "location": case.location,
                "case_type": case.case_type,
                "sequence": i + 1,
                "time_from_start": None  # 将在下面计算
            })
        
        # 计算相对时间
        if trajectory and trajectory[0]["timestamp"]:
            start_time = datetime.fromisoformat(trajectory[0]["timestamp"].replace("Z", "+00:00"))
            for point in trajectory:
                if point["timestamp"]:
                    point_time = datetime.fromisoformat(point["timestamp"].replace("Z", "+00:00"))
                    point["time_from_start"] = (point_time - start_time).total_seconds() / 3600  # 小时
        
        return trajectory

    @staticmethod
    def review_path_conditions(db: Session, case_ids: List[int]) -> Dict[str, Any]:
        """复盘已发生案件路径条件，不输出未来地点。"""
        trajectory = TrajectoryService.extract_trajectory(db, case_ids)
        analysis = TrajectoryService.analyze_trajectory_pattern(trajectory)
        if not trajectory:
            return {
                "case_ids": case_ids,
                "method": "path_condition_review",
                "facts": [],
                "path_conditions": [],
                "inferences": [],
                "information_gaps": ["缺少可用于复盘的案件坐标，暂不能分析路径条件。"],
                "reusable_suggestions": ["先补齐案件发生时间、经纬度和地点描述，再进行路径条件复盘。"],
                "analysis": analysis,
                "boundary": "仅复盘已发生案件路径条件，不做犯罪预测，不输出未来地点，不自动派发任务。",
            }

        facts = []
        for point in trajectory:
            facts.append({
                "case_id": point["case_id"],
                "case_number": point["case_number"],
                "time": point["timestamp"],
                "location": point["location"],
                "coordinate": {
                    "latitude": point["latitude"],
                    "longitude": point["longitude"],
                },
                "description": f"{point['case_number']} 已录入发生时间、地点和坐标。",
            })

        path_conditions: List[Dict[str, Any]] = []
        for i in range(1, len(trajectory)):
            previous = trajectory[i - 1]
            current = trajectory[i]
            distance_km = haversine_km(
                previous["latitude"],
                previous["longitude"],
                current["latitude"],
                current["longitude"],
            )
            bearing = calculate_bearing(
                previous["latitude"],
                previous["longitude"],
                current["latitude"],
                current["longitude"],
            )
            time_gap = None
            if previous.get("timestamp") and current.get("timestamp"):
                previous_time = datetime.fromisoformat(previous["timestamp"].replace("Z", "+00:00"))
                current_time = datetime.fromisoformat(current["timestamp"].replace("Z", "+00:00"))
                time_gap = round((current_time - previous_time).total_seconds() / 3600, 2)
            path_conditions.append({
                "type": "segment",
                "from_case_id": previous["case_id"],
                "to_case_id": current["case_id"],
                "label": f"{previous['case_number']} -> {current['case_number']}",
                "distance_km": round(distance_km, 2),
                "bearing_degree": round(bearing, 1),
                "time_gap_hours": time_gap,
                "detail": f"两案相距约 {round(distance_km, 2)} 公里，方向角约 {round(bearing, 1)} 度。"
                + (f" 时间差约 {time_gap} 小时。" if time_gap is not None else " 时间差缺少发生时间支撑。"),
            })

        nearby_assets = TrajectoryService._build_nearby_asset_conditions(db, trajectory)
        if nearby_assets:
            path_conditions.extend(nearby_assets)

        inferences = []
        direction = analysis.get("direction_analysis") or {}
        if len(trajectory) >= 2:
            inferences.append({
                "level": "medium",
                "statement": "案件点位之间存在可复盘的空间连续性，应结合道路、井点、监控和车辆信息人工确认链条关系。",
                "basis": analysis.get("insights", [])[:3],
            })
        if direction.get("is_linear") is True:
            inferences.append({
                "level": "low",
                "statement": "点位排列相对线性，可能与道路、管线或便道方向有关。",
                "basis": ["方向变化较少", *analysis.get("insights", [])[:2]],
            })
        elif direction.get("direction_changes", 0) > 0:
            inferences.append({
                "level": "low",
                "statement": "点位之间存在明显转向，应复核是否经过岔路、村屯、站库或转运节点。",
                "basis": [f"方向变化次数：{direction.get('direction_changes')}"],
            })

        information_gaps = []
        if any(point.get("timestamp") is None for point in trajectory):
            information_gaps.append("部分案件缺少发生时间，无法准确计算时间差和移动节奏。")
        if not nearby_assets:
            information_gaps.append("缺少井点、道路、村屯、监控等结构化空间要素，周边条件只能按案件点位复盘。")
        if len(trajectory) < 3:
            information_gaps.append("案件点少于 3 个，只能复盘相邻关系，不能形成稳定路径条件。")
        if not information_gaps:
            information_gaps.append("暂无阻断复盘的核心缺口，后续需人工核对实际路网和现场条件。")

        reusable_suggestions = [
            "将相邻案件的时间差、距离和方向作为链条复核依据，先核事实再确认推断。",
            "优先补齐周边井点、道路、村屯、监控和现场照片，支撑路径条件复盘。",
            "对复盘出的链条关系保留人工确认状态，避免把条件相似直接写成确定串案。",
        ]
        if nearby_assets:
            reusable_suggestions.append("对距离案件点最近的业务资产和公共地理要素建立引用，供报告和经验卡复用。")

        return {
            "case_ids": case_ids,
            "method": "path_condition_review",
            "facts": facts,
            "path_conditions": path_conditions,
            "inferences": inferences,
            "information_gaps": information_gaps,
            "reusable_suggestions": reusable_suggestions,
            "analysis": analysis,
            "boundary": "仅复盘已发生案件路径条件，不做犯罪预测，不输出未来地点，不自动派发任务。",
        }

    @staticmethod
    def _build_nearby_asset_conditions(db: Session, trajectory: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        assets = (
            db.query(JurisdictionAsset)
            .filter(JurisdictionAsset.latitude.isnot(None), JurisdictionAsset.longitude.isnot(None))
            .limit(300)
            .all()
        )
        if not assets:
            return []

        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for point in trajectory:
            nearest_by_type: Dict[str, Dict[str, Any]] = {}
            for asset in assets:
                distance = haversine_km(
                    point["latitude"],
                    point["longitude"],
                    asset.latitude,
                    asset.longitude,
                )
                current = nearest_by_type.get(asset.asset_type)
                if current is None or distance < current["distance_km"]:
                    nearest_by_type[asset.asset_type] = {
                        "case_id": point["case_id"],
                        "case_number": point["case_number"],
                        "asset_id": asset.id,
                        "asset_name": asset.name,
                        "asset_type": asset.asset_type,
                        "status": asset.status,
                        "distance_km": round(distance, 2),
                    }
            for asset_type, item in nearest_by_type.items():
                if item["distance_km"] <= 3:
                    grouped[asset_type].append(item)

        conditions = []
        labels = {
            "well": "井点邻近关系",
            "pipeline": "管线邻近关系",
            "station": "站库邻近关系",
            "camera": "监控邻近关系",
            "road": "道路邻近关系",
            "village": "村屯邻近关系",
        }
        for asset_type, items in grouped.items():
            nearest = sorted(items, key=lambda item: item["distance_km"])[:5]
            conditions.append({
                "type": "nearby_asset",
                "asset_type": asset_type,
                "label": labels.get(asset_type, f"{asset_type} 邻近关系"),
                "detail": "；".join(
                    f"{item['case_number']} 距 {item['asset_name']} 约 {item['distance_km']} 公里"
                    for item in nearest
                ),
                "items": nearest,
            })
        return conditions
    
    @staticmethod
    def analyze_trajectory_pattern(trajectory: List[Dict]) -> Dict:
        """
        分析轨迹模式
        
        Returns:
            轨迹分析结果：速度、方向、停留点等
        """
        if len(trajectory) < 2:
            return {
                "total_points": len(trajectory),
                "message": "轨迹点不足，无法分析"
            }
        
        # 计算速度（km/h）
        speeds = []
        directions = []  # 方向角（度）
        distances = []
        
        for i in range(1, len(trajectory)):
            p1 = trajectory[i-1]
            p2 = trajectory[i]
            
            if p1["latitude"] and p1["longitude"] and p2["latitude"] and p2["longitude"]:
                dist_km = haversine_km(
                    p1["latitude"], p1["longitude"],
                    p2["latitude"], p2["longitude"]
                )
                distances.append(dist_km)
                
                # 计算时间差（小时）
                if p1["time_from_start"] is not None and p2["time_from_start"] is not None:
                    time_diff_h = p2["time_from_start"] - p1["time_from_start"]
                    if time_diff_h > 0:
                        speed = dist_km / time_diff_h
                        speeds.append(speed)
                
                # 计算方向角
                bearing = calculate_bearing(
                    p1["latitude"], p1["longitude"],
                    p2["latitude"], p2["longitude"]
                )
                directions.append(bearing)
        
        # 识别停留点（速度很低的点）
        stay_points = []
        for i in range(len(trajectory)):
            if i > 0 and i < len(trajectory) - 1:
                # 检查前后速度
                if speeds and i-1 < len(speeds) and speeds[i-1] < 5:  # 速度低于5km/h
                    stay_points.append({
                        "case_id": trajectory[i]["case_id"],
                        "latitude": trajectory[i]["latitude"],
                        "longitude": trajectory[i]["longitude"],
                        "duration_estimate": "未知"
                    })
        
        # 计算总距离和平均速度
        total_distance = sum(distances)
        avg_speed = sum(speeds) / len(speeds) if speeds else 0
        
        # 方向变化分析
        direction_changes = []
        for i in range(1, len(directions)):
            change = abs(directions[i] - directions[i-1])
            if change > 180:
                change = 360 - change
            direction_changes.append(change)
        
        return {
            "total_points": len(trajectory),
            "total_distance_km": round(total_distance, 2),
            "average_speed_kmh": round(avg_speed, 2),
            "max_speed_kmh": round(max(speeds) if speeds else 0, 2),
            "min_speed_kmh": round(min(speeds) if speeds else 0, 2),
            "stay_points_count": len(stay_points),
            "stay_points": stay_points[:5],  # 只返回前5个
            "direction_analysis": {
                "average_direction": round(sum(directions) / len(directions), 1) if directions else None,
                "direction_changes": len([c for c in direction_changes if c > 45]),  # 大于45度的转向次数
                "is_linear": len([c for c in direction_changes if c > 45]) < len(directions) * 0.3  # 是否基本直线
            },
            "insights": [
                f"轨迹总长度: {round(total_distance, 2)} 公里",
                f"平均速度: {round(avg_speed, 2)} km/h" if avg_speed > 0 else "无法计算速度",
                f"识别出 {len(stay_points)} 个可能的停留点",
                "轨迹基本呈直线" if (direction_changes and len([c for c in direction_changes if c > 45]) < len(directions) * 0.3) else "轨迹有明显转向"
            ]
        }
    
    @staticmethod
    def predict_next_location(
        db: Session,
        case_ids: List[int],
        use_ai: bool = True
    ) -> Dict:
        """
        兼容旧入口：返回路径条件复盘口径，不再外推未来位置。
        
        Args:
            db: 数据库会话
            case_ids: 案件ID列表（用于分析历史模式）
            use_ai: 旧参数，仅为兼容保留，当前不会外推未来地点
            
        Returns:
            路径条件复盘结果。
        """
        review = TrajectoryService.review_path_conditions(db, case_ids)
        review["deprecated"] = True
        review["compatibility_note"] = "旧 predict 入口已改为路径条件复盘，不再输出未来地点。"
        review["use_ai_requested"] = bool(use_ai)
        return review
    
    @staticmethod
    def get_trajectory_replay_data(
        db: Session,
        case_ids: List[int],
        interval_seconds: int = 60
    ) -> Dict:
        """
        生成轨迹回放数据（用于前端动画）
        
        Args:
            db: 数据库会话
            case_ids: 案件ID列表
            interval_seconds: 回放时间间隔（秒）
            
        Returns:
            回放数据：时间序列的位置点
        """
        trajectory = TrajectoryService.extract_trajectory(db, case_ids)
        
        if not trajectory:
            return {
                "frames": [],
                "total_duration_seconds": 0
            }
        
        # 生成回放帧
        frames = []
        start_time = datetime.fromisoformat(trajectory[0]["timestamp"].replace("Z", "+00:00")) if trajectory[0]["timestamp"] else datetime.now()
        
        for i, point in enumerate(trajectory):
            point_time = datetime.fromisoformat(point["timestamp"].replace("Z", "+00:00")) if point["timestamp"] else start_time
            frames.append({
                "frame": i + 1,
                "timestamp": point_time.isoformat(),
                "latitude": point["latitude"],
                "longitude": point["longitude"],
                "case_id": point["case_id"],
                "case_number": point["case_number"],
                "location": point["location"]
            })
        
        total_duration = (frames[-1]["timestamp"] - frames[0]["timestamp"]).total_seconds() if len(frames) > 1 else 0
        
        return {
            "frames": frames,
            "total_duration_seconds": total_duration,
            "interval_seconds": interval_seconds,
            "start_time": frames[0]["timestamp"] if frames else None,
            "end_time": frames[-1]["timestamp"] if frames else None
        }
