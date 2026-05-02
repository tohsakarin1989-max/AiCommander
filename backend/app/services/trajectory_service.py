"""
轨迹分析与预测服务
基于案件时序位置数据，进行轨迹回放和AI位置预测
"""
from sqlalchemy.orm import Session
from app.models.case import Case
from app.utils.geo import haversine_km, calculate_bearing, destination_point
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
from app.utils.logger import logger
from app.ai.llm_providers import LLMProvider


class TrajectoryService:
    """轨迹分析与预测服务"""
    
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
            cases = sorted(cases, key=lambda c: c.occurred_time)
        
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
        预测下一个可能的位置
        
        Args:
            db: 数据库会话
            case_ids: 案件ID列表（用于分析历史模式）
            use_ai: 是否使用AI模型进行预测
            
        Returns:
            预测结果：可能的位置、概率、理由等
        """
        trajectory = TrajectoryService.extract_trajectory(db, case_ids)
        
        if len(trajectory) < 2:
            return {
                "prediction": None,
                "confidence": 0,
                "method": "insufficient_data",
                "message": "轨迹点不足，无法预测"
            }
        
        # 简单预测：基于速度和方向
        last_point = trajectory[-1]
        second_last = trajectory[-2]
        
        if not (last_point["latitude"] and last_point["longitude"] and 
                second_last["latitude"] and second_last["longitude"]):
            return {
                "prediction": None,
                "confidence": 0,
                "method": "insufficient_data",
                "message": "缺少位置信息"
            }
        
        # 计算最后一段的速度和方向
        dist_km = haversine_km(
            second_last["latitude"], second_last["longitude"],
            last_point["latitude"], last_point["longitude"]
        )
        
        time_diff_h = None
        if second_last["time_from_start"] is not None and last_point["time_from_start"] is not None:
            time_diff_h = last_point["time_from_start"] - second_last["time_from_start"]
        
        # 计算方向
        bearing_deg = calculate_bearing(
            second_last["latitude"], second_last["longitude"],
            last_point["latitude"], last_point["longitude"]
        )

        # 简单线性外推（假设保持当前速度和方向）
        # 预测未来1小时的位置
        if time_diff_h and time_diff_h > 0:
            speed_kmh = dist_km / time_diff_h
            future_distance_km = speed_kmh * 1.0  # 1小时后

            # 使用共享的目标点计算函数
            predicted_lat, predicted_lon = destination_point(
                last_point["latitude"], last_point["longitude"],
                bearing_deg, future_distance_km
            )
            
            # 如果使用AI，可以进一步优化预测
            if use_ai:
                # TODO: 调用AI模型进行更智能的预测
                # 可以考虑历史案件模式、地理特征、时间规律等
                pass
            
            return {
                "prediction": {
                    "latitude": round(predicted_lat, 6),
                    "longitude": round(predicted_lon, 6),
                    "estimated_time": (datetime.fromisoformat(last_point["timestamp"].replace("Z", "+00:00")) + timedelta(hours=1)).isoformat() if last_point["timestamp"] else None
                },
                "confidence": 0.6,  # 简单预测的置信度较低
                "method": "linear_extrapolation",
                "reasoning": f"基于最后一段轨迹的速度({round(speed_kmh, 2)} km/h)和方向进行线性外推",
                "assumptions": [
                    "保持当前移动速度和方向",
                    "预测时间窗口：1小时",
                    "未考虑地理障碍和实际路网"
                ]
            }
        else:
            return {
                "prediction": None,
                "confidence": 0,
                "method": "insufficient_data",
                "message": "无法计算速度，缺少时间信息"
            }
    
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

