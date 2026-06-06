"""
巡逻服务
处理巡逻记录的业务逻辑，包括风险评分更新
"""
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import uuid

from app.models.patrol import PatrolRecord, AreaRiskAssessment
from app.models.case import Case
from app.utils.logger import logger


class PatrolService:
    """巡逻服务类"""

    @staticmethod
    def generate_patrol_number() -> str:
        """生成外勤记录编号"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M")
        unique_id = uuid.uuid4().hex[:4].upper()
        return f"XL-{timestamp}-{unique_id}"

    @staticmethod
    def create_patrol(
        db: Session,
        area_name: str,
        patrol_type: str = "routine",
        area_coordinates: Optional[List[Dict]] = None,
        officer_count: int = 1,
        officer_names: Optional[str] = None,
        related_case_ids: Optional[List[int]] = None,
        related_deployment_id: Optional[int] = None,
        created_by: Optional[str] = None,
    ) -> PatrolRecord:
        """创建巡逻计划"""
        # 获取当前区域风险评分
        area_risk = PatrolService.get_or_create_area_risk(db, area_name, area_coordinates)

        patrol = PatrolRecord(
            patrol_number=PatrolService.generate_patrol_number(),
            patrol_type=patrol_type,
            area_name=area_name,
            area_coordinates=area_coordinates,
            officer_count=officer_count,
            officer_names=officer_names,
            related_case_ids=related_case_ids,
            related_deployment_id=related_deployment_id,
            risk_before=area_risk.risk_score,
            status="planned",
            created_by=created_by,
        )
        db.add(patrol)
        db.commit()
        db.refresh(patrol)
        return patrol

    @staticmethod
    def start_patrol(db: Session, patrol_id: int) -> PatrolRecord:
        """开始巡逻"""
        patrol = db.query(PatrolRecord).filter(PatrolRecord.id == patrol_id).first()
        if not patrol:
            raise ValueError(f"巡逻记录 {patrol_id} 不存在")

        patrol.status = "in_progress"
        patrol.start_time = datetime.utcnow()
        db.commit()
        db.refresh(patrol)
        return patrol

    @staticmethod
    def complete_patrol(
        db: Session,
        patrol_id: int,
        findings: Optional[str] = None,
        issues_found: int = 0,
        actions_taken: Optional[str] = None,
        patrol_route: Optional[List[Dict]] = None,
        evidence_photos: Optional[List[str]] = None,
        effectiveness_score: Optional[float] = None,
        feedback_notes: Optional[str] = None,
    ) -> PatrolRecord:
        """完成巡逻并记录结果"""
        patrol = db.query(PatrolRecord).filter(PatrolRecord.id == patrol_id).first()
        if not patrol:
            raise ValueError(f"巡逻记录 {patrol_id} 不存在")

        patrol.status = "completed"
        patrol.end_time = datetime.utcnow()
        patrol.findings = findings
        patrol.issues_found = issues_found
        patrol.actions_taken = actions_taken
        patrol.patrol_route = patrol_route
        patrol.evidence_photos = evidence_photos
        patrol.effectiveness_score = effectiveness_score
        patrol.feedback_notes = feedback_notes

        db.commit()

        # 更新区域风险评分
        new_risk = PatrolService.update_area_risk_after_patrol(
            db, patrol.area_name, patrol.area_coordinates, patrol
        )
        patrol.risk_after = new_risk

        db.commit()
        db.refresh(patrol)
        return patrol

    @staticmethod
    def get_or_create_area_risk(
        db: Session,
        area_name: str,
        area_coordinates: Optional[List[Dict]] = None
    ) -> AreaRiskAssessment:
        """获取或创建区域风险评估记录"""
        area_risk = db.query(AreaRiskAssessment).filter(
            AreaRiskAssessment.area_name == area_name
        ).first()

        if not area_risk:
            area_risk = AreaRiskAssessment(
                area_name=area_name,
                area_coordinates=area_coordinates,
                risk_score=50,  # 默认中等风险
                risk_level="medium",
                risk_history=[],
            )
            db.add(area_risk)
            db.commit()
            db.refresh(area_risk)

        return area_risk

    @staticmethod
    def calculate_area_risk_score(
        db: Session,
        area_name: str,
        area_coordinates: Optional[List[Dict]] = None
    ) -> Dict:
        """计算区域风险评分"""
        now = datetime.utcnow()
        day_30_ago = now - timedelta(days=30)
        day_7_ago = now - timedelta(days=7)

        # 获取区域内案件数量（简化版：按区域名称匹配）
        recent_cases_30d = db.query(Case).filter(
            Case.location.ilike(f"%{area_name}%"),
            Case.occurred_time >= day_30_ago
        ).all()
        recent_cases_7d = [
            case for case in recent_cases_30d
            if case.occurred_time and case.occurred_time >= day_7_ago
        ]

        case_count_30d = len(recent_cases_30d)
        case_count_7d = len(recent_cases_7d)
        oil_case_count = sum(1 for c in recent_cases_30d if c.oil_type or c.oil_nature or c.oil_volume is not None)
        vehicle_case_count = sum(1 for c in recent_cases_30d if c.vehicle_info or getattr(c, "vehicles", None))
        low_quality_count = sum(
            1
            for c in recent_cases_30d
            if isinstance(c.quality_score, (int, float)) and c.quality_score < 60
        )
        night_case_count = sum(
            1
            for c in recent_cases_30d
            if c.occurred_time and (c.occurred_time.hour >= 20 or c.occurred_time.hour < 6)
        )
        source_distribution: Dict[str, int] = {}
        for c in recent_cases_30d:
            key = c.source_type or "未标注"
            source_distribution[key] = source_distribution.get(key, 0) + 1

        # 获取巡逻记录
        patrol_count_30d = db.query(func.count(PatrolRecord.id)).filter(
            PatrolRecord.area_name == area_name,
            PatrolRecord.status == "completed",
            PatrolRecord.end_time >= day_30_ago
        ).scalar() or 0

        last_patrol = db.query(PatrolRecord).filter(
            PatrolRecord.area_name == area_name,
            PatrolRecord.status == "completed"
        ).order_by(PatrolRecord.end_time.desc()).first()

        last_patrol_date = last_patrol.end_time if last_patrol else None
        days_since_patrol = (now - last_patrol_date).days if last_patrol_date else 999

        # 计算风险评分（基于多个因素）
        base_score = 30  # 基础分

        # 案件因素（案件越多，风险越高）
        case_factor = min(case_count_30d * 5 + case_count_7d * 10, 40)
        oil_factor = min(oil_case_count * 3, 10)
        vehicle_factor = min(vehicle_case_count * 2, 8)
        night_factor = min(night_case_count * 2, 8)
        quality_factor = min(low_quality_count * 2, 8)

        # 巡逻因素（巡逻越少，风险越高）
        if patrol_count_30d == 0:
            patrol_factor = 20
        elif patrol_count_30d < 3:
            patrol_factor = 10
        else:
            patrol_factor = 0

        # 时间因素（距上次巡逻时间越长，风险越高）
        if days_since_patrol > 14:
            time_factor = 10
        elif days_since_patrol > 7:
            time_factor = 5
        else:
            time_factor = 0

        risk_score = min(
            base_score
            + case_factor
            + oil_factor
            + vehicle_factor
            + night_factor
            + quality_factor
            + patrol_factor
            + time_factor,
            100,
        )

        # 确定风险等级
        if risk_score >= 80:
            risk_level = "critical"
        elif risk_score >= 60:
            risk_level = "high"
        elif risk_score >= 40:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "risk_score": risk_score,
            "risk_level": risk_level,
            "case_count_30d": case_count_30d,
            "case_count_7d": case_count_7d,
            "patrol_count_30d": patrol_count_30d,
            "last_patrol_date": last_patrol_date,
            "days_since_patrol": days_since_patrol,
            "oil_case_count_30d": oil_case_count,
            "vehicle_case_count_30d": vehicle_case_count,
            "night_case_count_30d": night_case_count,
            "low_quality_case_count_30d": low_quality_count,
            "source_distribution": source_distribution,
            "risk_factors": {
                "base": base_score,
                "case": case_factor,
                "oil": oil_factor,
                "vehicle": vehicle_factor,
                "night": night_factor,
                "quality_gap": quality_factor,
                "patrol": patrol_factor,
                "time_since_last_patrol": time_factor,
            },
        }

    @staticmethod
    def update_area_risk_after_patrol(
        db: Session,
        area_name: str,
        area_coordinates: Optional[List[Dict]],
        patrol: PatrolRecord
    ) -> float:
        """巡逻完成后更新区域风险评分"""
        area_risk = PatrolService.get_or_create_area_risk(db, area_name, area_coordinates)
        old_score = area_risk.risk_score

        # 重新计算风险评分
        risk_data = PatrolService.calculate_area_risk_score(db, area_name, area_coordinates)

        # 根据巡逻效果进一步调整
        effectiveness = patrol.effectiveness_score or 70
        if effectiveness >= 80:
            adjustment = -5  # 高效巡逻降低风险
        elif effectiveness < 50:
            adjustment = 5  # 低效巡逻可能表示区域问题较多
        else:
            adjustment = 0

        new_score = max(0, min(100, risk_data["risk_score"] + adjustment))

        # 更新记录
        area_risk.risk_score = new_score
        area_risk.risk_level = risk_data["risk_level"]
        area_risk.case_count_30d = risk_data["case_count_30d"]
        area_risk.case_count_7d = risk_data["case_count_7d"]
        area_risk.patrol_count_30d = risk_data["patrol_count_30d"]
        area_risk.last_patrol_date = patrol.end_time
        area_risk.days_since_patrol = 0

        # 记录历史
        history = area_risk.risk_history or []
        history.append({
            "date": datetime.utcnow().isoformat(),
            "score": new_score,
            "old_score": old_score,
            "reason": f"巡逻完成（编号：{patrol.patrol_number}），效果评分：{effectiveness}",
        })
        area_risk.risk_history = history[-50:]  # 保留最近50条

        db.commit()

        logger.info(
            f"区域 {area_name} 风险评分已更新：{old_score:.1f} -> {new_score:.1f}"
        )

        return new_score

    @staticmethod
    def get_patrols(
        db: Session,
        skip: int = 0,
        limit: int = 100,
        status: Optional[str] = None,
        area_name: Optional[str] = None,
    ) -> List[PatrolRecord]:
        """获取巡逻记录列表"""
        query = db.query(PatrolRecord)

        if status:
            query = query.filter(PatrolRecord.status == status)
        if area_name:
            query = query.filter(PatrolRecord.area_name.ilike(f"%{area_name}%"))

        return query.order_by(PatrolRecord.created_at.desc()).offset(skip).limit(limit).all()

    @staticmethod
    def get_patrol(db: Session, patrol_id: int) -> Optional[PatrolRecord]:
        """获取单个巡逻记录"""
        return db.query(PatrolRecord).filter(PatrolRecord.id == patrol_id).first()

    @staticmethod
    def get_area_risks(
        db: Session,
        skip: int = 0,
        limit: int = 100,
        min_risk: Optional[float] = None,
    ) -> List[AreaRiskAssessment]:
        """获取区域风险评估列表"""
        query = db.query(AreaRiskAssessment)

        if min_risk is not None:
            query = query.filter(AreaRiskAssessment.risk_score >= min_risk)

        return query.order_by(AreaRiskAssessment.risk_score.desc()).offset(skip).limit(limit).all()

    @staticmethod
    def refresh_all_area_risks(db: Session) -> int:
        """刷新所有区域的风险评分"""
        areas = db.query(AreaRiskAssessment).all()
        count = 0

        for area in areas:
            try:
                risk_data = PatrolService.calculate_area_risk_score(
                    db, area.area_name, area.area_coordinates
                )
                area.risk_score = risk_data["risk_score"]
                area.risk_level = risk_data["risk_level"]
                area.case_count_30d = risk_data["case_count_30d"]
                area.case_count_7d = risk_data["case_count_7d"]
                area.patrol_count_30d = risk_data["patrol_count_30d"]
                area.last_patrol_date = risk_data["last_patrol_date"]
                area.days_since_patrol = risk_data["days_since_patrol"]
                count += 1
            except Exception as e:
                logger.error(f"刷新区域 {area.area_name} 风险评分失败: {e}")

        db.commit()
        return count

    @staticmethod
    def calculate_smart_schedule(db: Session, days: int = 90) -> Dict:
        """
        基于历史案件时间分布计算智能巡逻时段建议

        逻辑：
        1. 查询最近 days 天内所有案件
        2. 按小时统计频次，合并相邻高发小时为时间窗口
        3. 取频次最高的 3 个时间窗口
        4. 按星期统计频次，取 TOP 3 作为 weekday_priority
        5. case_count > total*25% 为 high，> 15% 为 medium，其余为 low
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        cases = db.query(Case).filter(Case.occurred_time >= cutoff).all()

        total = len(cases)
        if total == 0:
            return {
                "recommended_windows": [],
                "weekday_priority": [],
                "total_cases_analyzed": 0,
                "analysis_days": days,
            }

        # 按小时统计频次（0-23）
        hour_counts: Dict[int, int] = {h: 0 for h in range(24)}
        weekday_counts: Dict[int, int] = {d: 0 for d in range(7)}
        source_counts: Dict[str, int] = {}
        oil_nature_counts: Dict[str, int] = {}
        low_quality_case_count = 0
        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

        for case in cases:
            if case.occurred_time:
                hour_counts[case.occurred_time.hour] += 1
                weekday_counts[case.occurred_time.weekday()] += 1
            source_key = case.source_type or "未标注"
            source_counts[source_key] = source_counts.get(source_key, 0) + 1
            if case.oil_nature:
                oil_nature_counts[case.oil_nature] = oil_nature_counts.get(case.oil_nature, 0) + 1
            if isinstance(case.quality_score, (int, float)) and case.quality_score < 60:
                low_quality_case_count += 1

        # 计算平均每小时案件数，以均值的 1.2 倍作为"高发"阈值
        avg_per_hour = total / 24
        high_threshold = avg_per_hour * 1.2

        # 合并相邻高发小时为时间窗口（循环24小时处理跨天情况）
        # 标记哪些小时属于高发
        is_high = [hour_counts[h] >= high_threshold for h in range(24)]

        # 提取连续高发段（循环边界处理：先找所有段再处理跨 0 点的情况）
        windows = []
        in_window = False
        win_start = 0
        for h in range(24):
            if is_high[h] and not in_window:
                in_window = True
                win_start = h
            elif not is_high[h] and in_window:
                in_window = False
                win_count = sum(hour_counts[x] for x in range(win_start, h))
                windows.append((win_start, h, win_count))
        if in_window:
            # 最后一段延续到 23
            win_count = sum(hour_counts[x] for x in range(win_start, 24))
            windows.append((win_start, 24, win_count))

        # 若窗口不足 3 个，则取频次最高的单小时作为补充
        if len(windows) < 3:
            # 按频次排序的小时
            sorted_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)
            covered_hours = set()
            for win in windows:
                covered_hours.update(range(win[0], win[1]))
            for h, cnt in sorted_hours:
                if h not in covered_hours and cnt > 0:
                    windows.append((h, h + 1, cnt))
                    covered_hours.add(h)
                if len(windows) >= 3:
                    break

        # 按案件数降序排序，取前 3
        windows.sort(key=lambda x: x[2], reverse=True)
        top_windows = windows[:3]

        def risk_level_from_count(count: int) -> str:
            if count > total * 0.25:
                return "high"
            if count > total * 0.15:
                return "medium"
            return "low"

        recommended_windows = []
        for start_h, end_h, cnt in top_windows:
            # end_h 可能为 24（跨天表示），对显示做取模处理
            end_display = end_h % 24
            label = f"{start_h:02d}:00-{end_display:02d}:00"
            recommended_windows.append({
                "start_hour": start_h,
                "end_hour": end_h % 24,
                "label": label,
                "case_count": cnt,
                "percentage": round(cnt / total * 100, 1),
                "risk_level": risk_level_from_count(cnt),
            })

        # 按星期统计，取 TOP 3
        sorted_weekdays = sorted(weekday_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        weekday_priority = [
            {
                "weekday": wd,
                "name": weekday_names[wd],
                "case_count": cnt,
                "percentage": round(cnt / total * 100, 1),
            }
            for wd, cnt in sorted_weekdays if cnt > 0
        ]
        source_priority = [
            {"source_type": k, "case_count": v, "percentage": round(v / total * 100, 1)}
            for k, v in sorted(source_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        ]
        oil_nature_priority = [
            {"oil_nature": k, "case_count": v, "percentage": round(v / total * 100, 1)}
            for k, v in sorted(oil_nature_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        ]

        return {
            "recommended_windows": recommended_windows,
            "weekday_priority": weekday_priority,
            "source_priority": source_priority,
            "oil_nature_priority": oil_nature_priority,
            "low_quality_case_count": low_quality_case_count,
            "data_quality_note": "低质量案件可能降低巡逻规划精度，建议先补齐地点、线索来源、涉案车辆/人员和处置字段。",
            "total_cases_analyzed": total,
            "analysis_days": days,
        }

    @staticmethod
    def build_case_driven_patrol_plan(
        db: Session,
        days: int = 90,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """按案件信息生成区域化巡逻规划，优先使用新补齐的来源、油品、车辆和质量字段。"""
        cutoff = datetime.utcnow() - timedelta(days=days)
        cases = (
            db.query(Case)
            .filter(Case.occurred_time >= cutoff)
            .order_by(Case.occurred_time.desc())
            .all()
        )

        area_map: Dict[str, Dict[str, Any]] = {}
        missing_geo_count = 0
        low_quality_count = 0

        for case in cases:
            area_name = case.location or case.report_unit or "未标注区域"
            if area_name not in area_map:
                area_map[area_name] = {
                    "area_name": area_name,
                    "case_ids": [],
                    "cases": [],
                    "hour_counts": {h: 0 for h in range(24)},
                    "source_counts": {},
                    "oil_nature_counts": {},
                    "quality_scores": [],
                    "latitudes": [],
                    "longitudes": [],
                    "vehicle_case_count": 0,
                    "oil_case_count": 0,
                    "night_case_count": 0,
                    "missing_fields": {},
                }
            area = area_map[area_name]
            area["case_ids"].append(case.id)
            area["cases"].append(case)
            if case.occurred_time:
                area["hour_counts"][case.occurred_time.hour] += 1
                if case.occurred_time.hour >= 20 or case.occurred_time.hour < 6:
                    area["night_case_count"] += 1
            if case.latitude is not None and case.longitude is not None:
                area["latitudes"].append(case.latitude)
                area["longitudes"].append(case.longitude)
            else:
                missing_geo_count += 1
            source_key = case.source_type or "未标注"
            area["source_counts"][source_key] = area["source_counts"].get(source_key, 0) + 1
            if case.oil_nature:
                area["oil_nature_counts"][case.oil_nature] = area["oil_nature_counts"].get(case.oil_nature, 0) + 1
            if case.oil_type or case.oil_nature or case.oil_volume is not None:
                area["oil_case_count"] += 1
            if case.vehicle_info or getattr(case, "vehicles", None):
                area["vehicle_case_count"] += 1
            if isinstance(case.quality_score, (int, float)):
                area["quality_scores"].append(case.quality_score)
                if case.quality_score < 60:
                    low_quality_count += 1
            if isinstance(case.quality_issues, dict):
                for item in case.quality_issues.get("missing_required", []):
                    if isinstance(item, dict) and item.get("label"):
                        label = item["label"]
                        area["missing_fields"][label] = area["missing_fields"].get(label, 0) + 1

        def build_windows(hour_counts: Dict[int, int], total: int) -> List[Dict[str, Any]]:
            if total <= 0:
                return []
            ranked = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)
            return [
                {
                    "start_hour": hour,
                    "end_hour": (hour + 1) % 24,
                    "label": f"{hour:02d}:00-{(hour + 1) % 24:02d}:00",
                    "case_count": count,
                    "risk_level": "high" if count >= max(2, total * 0.3) else "medium",
                }
                for hour, count in ranked[:3]
                if count > 0
            ]

        areas = []
        for area in area_map.values():
            case_count = len(area["case_ids"])
            avg_quality = (
                sum(area["quality_scores"]) / len(area["quality_scores"])
                if area["quality_scores"]
                else 50
            )
            priority_score = min(
                100,
                case_count * 18
                + area["oil_case_count"] * 8
                + area["vehicle_case_count"] * 6
                + area["night_case_count"] * 6
                + max(0, 70 - avg_quality) * 0.5,
            )
            patrol_focus = []
            if area["night_case_count"]:
                patrol_focus.append("夜间重点巡控")
            if area["vehicle_case_count"]:
                patrol_focus.append("可疑车辆盘查")
            if area["oil_case_count"]:
                patrol_focus.append("涉油设施与油品流向核查")
            if any(k in area["source_counts"] for k in ("群众举报", "技防预警")):
                patrol_focus.append("举报线索和技防预警回访")
            if area["missing_fields"]:
                patrol_focus.append("现场补录缺失案件信息")

            missing_rank = sorted(area["missing_fields"].items(), key=lambda x: x[1], reverse=True)
            completion_actions = [
                f"补齐{label}（涉及 {count} 起）"
                for label, count in missing_rank[:5]
            ]
            if not area["latitudes"]:
                completion_actions.append("补充该区域案件经纬度，提升路线规划精度")

            areas.append({
                "area_name": area["area_name"],
                "case_count": case_count,
                "case_ids": area["case_ids"],
                "center": {
                    "latitude": sum(area["latitudes"]) / len(area["latitudes"]) if area["latitudes"] else None,
                    "longitude": sum(area["longitudes"]) / len(area["longitudes"]) if area["longitudes"] else None,
                },
                "priority_score": round(priority_score, 2),
                "risk_level": "critical" if priority_score >= 85 else "high" if priority_score >= 65 else "medium" if priority_score >= 40 else "low",
                "average_quality_score": round(avg_quality, 2),
                "source_types": [
                    key
                    for key, _ in sorted(area["source_counts"].items(), key=lambda x: x[1], reverse=True)
                ],
                "oil_natures": [
                    key
                    for key, _ in sorted(area["oil_nature_counts"].items(), key=lambda x: x[1], reverse=True)
                ],
                "recommended_windows": build_windows(area["hour_counts"], case_count),
                "patrol_focus": patrol_focus or ["常规巡控"],
                "completion_actions": completion_actions,
            })

        areas.sort(key=lambda item: item["priority_score"], reverse=True)

        return {
            "generated_at": datetime.utcnow().isoformat(),
            "analysis_days": days,
            "area_count": len(areas),
            "areas": areas[:limit],
            "data_quality": {
                "total_cases": len(cases),
                "missing_geo_case_count": missing_geo_count,
                "low_quality_case_count": low_quality_count,
                "note": "巡逻规划已纳入案件质量，低质量或缺坐标案件会进入补录动作。",
            },
        }
