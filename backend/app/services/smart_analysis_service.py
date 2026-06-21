"""
智能研判服务
一键串联多个分析模块，生成综合研判报告
"""
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models.case import Case
from app.services.case_intelligence_service import CaseIntelligenceService
from app.services.gang_analysis_service import GangAnalysisService
from app.services.geo_analysis_service import GeoAnalysisService
from app.services.deployment_service import DeploymentService
from app.services.jurisdiction_service import JurisdictionService
from app.utils.logger import logger


class SmartAnalysisService:
    """智能研判服务 - 一键完成多维度分析"""

    def __init__(self, db: Session):
        self.db = db
        self.gang_service = GangAnalysisService
        self.geo_service = GeoAnalysisService

    async def analyze(
        self,
        time_window_days: int = 90,
        min_cases: int = 2,
        include_deployment: bool = True,
    ) -> Dict[str, Any]:
        """
        一键智能研判

        Args:
            time_window_days: 分析时间窗口（天）
            min_cases: 最少案件数阈值
            include_deployment: 是否生成部署建议

        Returns:
            综合研判报告
        """
        start_time = datetime.now()
        report = {
            "analysis_time": start_time.isoformat(),
            "time_window_days": time_window_days,
            "modules": {},
            "summary": {},
            "recommendations": [],
            "priority_actions": [],
        }

        try:
            # 并行执行多个分析模块
            tasks = [
                self._analyze_hotspots(time_window_days, min_cases),
                self._analyze_gangs(time_window_days, min_cases),
                self._analyze_patterns(time_window_days),
                self._analyze_jurisdiction(),
                self._analyze_case_intelligence(time_window_days),
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 处理热点分析结果
            if not isinstance(results[0], Exception):
                report["modules"]["hotspots"] = results[0]
            else:
                logger.warning(f"热点分析失败: {results[0]}")
                report["modules"]["hotspots"] = {"error": str(results[0])}

            # 处理团伙分析结果
            if not isinstance(results[1], Exception):
                report["modules"]["gangs"] = results[1]
            else:
                logger.warning(f"团伙分析失败: {results[1]}")
                report["modules"]["gangs"] = {"error": str(results[1])}

            # 处理模式分析结果
            if not isinstance(results[2], Exception):
                report["modules"]["patterns"] = results[2]
            else:
                logger.warning(f"模式分析失败: {results[2]}")
                report["modules"]["patterns"] = {"error": str(results[2])}

            # 处理辖区底座与预防工作台结果
            if not isinstance(results[3], Exception):
                report["modules"]["jurisdiction"] = results[3]
            else:
                logger.warning(f"辖区底座分析失败: {results[3]}")
                report["modules"]["jurisdiction"] = {"error": str(results[3])}

            # 处理案件研判工作台结果
            if not isinstance(results[4], Exception):
                report["modules"]["case_intelligence"] = results[4]
            else:
                logger.warning(f"案件研判工作台分析失败: {results[4]}")
                report["modules"]["case_intelligence"] = {"error": str(results[4])}

            # 生成部署建议
            if include_deployment:
                try:
                    deployment = await self._generate_deployment_suggestions(report)
                    report["modules"]["deployment"] = deployment
                except Exception as e:
                    logger.warning(f"部署建议生成失败: {e}")
                    report["modules"]["deployment"] = {"error": str(e)}

            # 生成综合摘要
            report["summary"] = self._generate_summary(report)

            # 生成优先行动建议
            report["priority_actions"] = self._generate_priority_actions(report)

            # 生成综合建议
            report["recommendations"] = self._generate_recommendations(report)

            # 计算分析耗时
            end_time = datetime.now()
            report["duration_seconds"] = (end_time - start_time).total_seconds()

        except Exception as e:
            logger.error(f"智能研判失败: {e}")
            report["error"] = str(e)

        return report

    async def _analyze_hotspots(
        self,
        time_window_days: int,
        min_cases: int,
    ) -> Dict[str, Any]:
        """分析热点区域"""
        # 获取时间范围内的案件
        cutoff_date = datetime.now() - timedelta(days=time_window_days)
        cases = (
            self.db.query(Case)
            .filter(Case.occurred_time >= cutoff_date)
            .filter(Case.latitude.isnot(None), Case.longitude.isnot(None))
            .all()
        )

        if len(cases) < min_cases:
            return {
                "status": "insufficient_data",
                "case_count": len(cases),
                "hotspots": [],
            }

        # 使用地理分析服务查找热点
        hotspots = self.geo_service.find_hotspots(
            cases=cases,
            radius_km=0.5,
            min_cases=min_cases,
        )

        # 按风险评分排序
        hotspots_sorted = sorted(hotspots, key=lambda x: x.get("risk_score", 0), reverse=True)

        return {
            "status": "success",
            "case_count": len(cases),
            "hotspot_count": len(hotspots_sorted),
            "hotspots": hotspots_sorted[:10],  # 返回前10个热点
            "high_risk_count": len([h for h in hotspots_sorted if h.get("risk_score", 0) >= 70]),
        }

    async def _analyze_gangs(
        self,
        time_window_days: int,
        min_cases: int,
    ) -> Dict[str, Any]:
        """分析潜在团伙"""
        try:
            gangs = self.gang_service.identify_gangs(
                db=self.db,
                min_similarity=0.5,
                min_cases=min_cases,
                time_window_days=time_window_days,
            )

            # 计算统计
            high_risk = [g for g in gangs if g.get("risk_score", 0) >= 60]
            total_cases = sum(g.get("case_count", 0) for g in gangs)

            return {
                "status": "success",
                "gang_count": len(gangs),
                "high_risk_gang_count": len(high_risk),
                "total_cases_in_gangs": total_cases,
                "top_gangs": gangs[:5],  # 返回前5个团伙
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _analyze_patterns(
        self,
        time_window_days: int,
    ) -> Dict[str, Any]:
        """分析作案模式"""
        cutoff_date = datetime.now() - timedelta(days=time_window_days)
        cases = (
            self.db.query(Case)
            .filter(Case.occurred_time >= cutoff_date)
            .all()
        )

        if not cases:
            return {"status": "no_data", "patterns": {}}

        # 时间模式分析
        hour_distribution = {}
        day_distribution = {}
        type_distribution = {}
        modus_distribution = {}

        for case in cases:
            if case.occurred_time:
                hour = case.occurred_time.hour
                day = case.occurred_time.weekday()
                hour_distribution[hour] = hour_distribution.get(hour, 0) + 1
                day_distribution[day] = day_distribution.get(day, 0) + 1

            if case.case_type:
                type_distribution[case.case_type] = type_distribution.get(case.case_type, 0) + 1

            if case.modus_operandi:
                modus_distribution[case.modus_operandi] = modus_distribution.get(case.modus_operandi, 0) + 1

        # 找出高发时段
        peak_hours = sorted(hour_distribution.items(), key=lambda x: x[1], reverse=True)[:3]
        peak_days = sorted(day_distribution.items(), key=lambda x: x[1], reverse=True)[:3]

        day_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

        return {
            "status": "success",
            "case_count": len(cases),
            "patterns": {
                "peak_hours": [{"hour": h, "count": c} for h, c in peak_hours],
                "peak_days": [{"day": day_names[d], "count": c} for d, c in peak_days],
                "case_types": dict(sorted(type_distribution.items(), key=lambda x: x[1], reverse=True)[:5]),
                "modus_operandi": dict(sorted(modus_distribution.items(), key=lambda x: x[1], reverse=True)[:5]),
            },
        }

    async def _analyze_jurisdiction(self) -> Dict[str, Any]:
        """把辖区底座质量、相似风险点和控点建议纳入一键研判。"""
        data_quality = JurisdictionService.audit_data_quality(self.db)
        summary = JurisdictionService.summarize_assets(self.db)
        latest_case = (
            self.db.query(Case)
            .filter(Case.latitude.isnot(None), Case.longitude.isnot(None))
            .order_by(Case.occurred_time.desc().nullslast(), Case.id.desc())
            .first()
        )

        if latest_case:
            patrol_plan = JurisdictionService.build_patrol_plan(
                self.db,
                case_id=latest_case.id,
                limit=5,
            )
            similar_targets = JurisdictionService.find_similar_targets(
                self.db,
                case_id=latest_case.id,
                limit=5,
            )
            risk_context = JurisdictionService.build_case_risk_context(
                self.db,
                latest_case.id,
            )
            case_id = latest_case.id
        else:
            patrol_plan = JurisdictionService.build_patrol_plan(self.db, limit=5)
            similar_targets = {"items": []}
            risk_context = None
            case_id = None

        return {
            "status": "success",
            "case_id": case_id,
            "asset_summary": summary,
            "data_quality": data_quality,
            "risk_context": risk_context,
            "similar_targets": similar_targets,
            "patrol_plan": patrol_plan,
        }

    async def _analyze_case_intelligence(self, time_window_days: int) -> Dict[str, Any]:
        """纳入案件研判工作台：标签、相似条件、现场要素、防控参考和复盘报告。"""
        latest_case = (
            self.db.query(Case)
            .order_by(Case.occurred_time.desc().nullslast(), Case.id.desc())
            .first()
        )
        workbench = CaseIntelligenceService.build_workbench(
            self.db,
            case_id=latest_case.id if latest_case else None,
            days=time_window_days,
            limit=5,
        )
        return {
            "status": "success",
            "case_id": latest_case.id if latest_case else None,
            "selected_case": workbench.get("selected_case"),
            "tag_count": len(workbench.get("feature_tags", {}).get("tags", [])),
            "similar_case_count": len(workbench.get("similar_cases", {}).get("items", [])),
            "suggestion_count": workbench.get("prevention_suggestions", {}).get("suggestion_count", 0),
            "area_profile_count": workbench.get("area_profiles", {}).get("profile_count", 0),
            "insights": workbench.get("spatiotemporal", {}).get("insights", [])[:5],
            "top_suggestions": workbench.get("prevention_suggestions", {}).get("items", [])[:5],
            "boundary": workbench.get("prevention_suggestions", {}).get("boundary"),
        }

    async def _generate_deployment_suggestions(
        self,
        report: Dict[str, Any],
    ) -> Dict[str, Any]:
        """基于分析结果生成部署建议"""
        suggestions = []

        # 基于热点生成关注区域建议
        hotspots = report.get("modules", {}).get("hotspots", {}).get("hotspots", [])
        for hotspot in hotspots[:5]:
            if hotspot.get("risk_score", 0) >= 50:
                suggestions.append({
                    "type": "area_attention",
                    "priority": "high" if hotspot.get("risk_score", 0) >= 70 else "medium",
                    "location": f"热点区域（{hotspot.get('case_count', 0)}起案件）",
                    "coordinates": hotspot.get("center"),
                    "action": "纳入重点关注区域清单",
                    "reason": f"近期发案{hotspot.get('case_count', 0)}起，风险评分{hotspot.get('risk_score', 0)}",
                })

        # 基于旧相似聚类模块生成条件复盘建议
        gangs = report.get("modules", {}).get("gangs", {}).get("top_gangs", [])
        for gang in gangs[:3]:
            if gang.get("risk_score", 0) >= 60:
                suggestions.append({
                    "type": "condition_review",
                    "priority": "high",
                    "target": f"相似条件组（{gang.get('case_count', 0)}起关联案件）",
                    "action": "复核共同作案条件",
                    "focus": gang.get("modus_operandi", []),
                    "reason": f"条件组风险评分{gang.get('risk_score', 0)}，涉及案件{gang.get('case_count', 0)}起",
                })

        # 基于时间模式生成值班建议
        patterns = report.get("modules", {}).get("patterns", {}).get("patterns", {})
        peak_hours = patterns.get("peak_hours", [])
        if peak_hours:
            hour_ranges = [f"{h['hour']}:00-{(h['hour']+1)%24}:00" for h in peak_hours]
            suggestions.append({
                "type": "schedule",
                "priority": "medium",
                "action": "纳入高发时段关注",
                "time_slots": hour_ranges,
                "reason": f"高发时段：{', '.join(hour_ranges)}",
            })

        # 基于辖区底座生成控点建议
        jurisdiction = report.get("modules", {}).get("jurisdiction", {})
        control_points = jurisdiction.get("patrol_plan", {}).get("control_points", [])
        for point in control_points[:5]:
            asset = point.get("asset", {})
            suggestions.append({
                "type": "jurisdiction_reference",
                "priority": "high" if point.get("priority", 3) <= 2 else "medium",
                "location": asset.get("name", "相似风险点"),
                "coordinates": {
                    "latitude": asset.get("latitude"),
                    "longitude": asset.get("longitude"),
                },
                "action": "纳入防控参考清单",
                "reason": point.get("reason", "来源于辖区底座和已破案件相似条件。"),
            })

        # 直接复用案件研判工作台生成的建议草案
        case_intelligence = report.get("modules", {}).get("case_intelligence", {})
        for item in case_intelligence.get("top_suggestions", [])[:5]:
            suggestions.append({
                "type": "case_intelligence",
                "priority": item.get("priority", "medium"),
                "action": item.get("title", "案件研判建议"),
                "reason": item.get("action", "来源于案件研判工作台。"),
            })

        return {
            "status": "success",
            "suggestion_count": len(suggestions),
            "suggestions": suggestions,
        }

    def _generate_summary(self, report: Dict[str, Any]) -> Dict[str, Any]:
        """生成综合摘要"""
        modules = report.get("modules", {})

        hotspot_data = modules.get("hotspots", {})
        gang_data = modules.get("gangs", {})
        pattern_data = modules.get("patterns", {})
        jurisdiction_data = modules.get("jurisdiction", {})

        # 计算整体风险等级
        risk_factors = []

        high_risk_hotspots = hotspot_data.get("high_risk_count", 0)
        if high_risk_hotspots > 0:
            risk_factors.append(f"{high_risk_hotspots}个高风险热点区域")

        high_risk_gangs = gang_data.get("high_risk_gang_count", 0)
        if high_risk_gangs > 0:
            risk_factors.append(f"{high_risk_gangs}个高关注条件组")

        # 计算综合风险等级
        risk_score = 0
        if high_risk_hotspots > 3:
            risk_score += 30
        elif high_risk_hotspots > 0:
            risk_score += 15

        if high_risk_gangs > 2:
            risk_score += 40
        elif high_risk_gangs > 0:
            risk_score += 20

        case_count = pattern_data.get("case_count", 0)
        if case_count > 50:
            risk_score += 20
        elif case_count > 20:
            risk_score += 10

        jurisdiction_quality = jurisdiction_data.get("data_quality", {}).get("coverage_score")
        if isinstance(jurisdiction_quality, (int, float)) and jurisdiction_quality < 60:
            risk_score += 10
            risk_factors.append("辖区底座质量不足")

        risk_level = "critical" if risk_score >= 70 else "high" if risk_score >= 50 else "medium" if risk_score >= 30 else "low"

        return {
            "overall_risk_level": risk_level,
            "overall_risk_score": risk_score,
            "risk_factors": risk_factors,
            "case_count": case_count,
            "hotspot_count": hotspot_data.get("hotspot_count", 0),
            "gang_count": gang_data.get("gang_count", 0),
            "jurisdiction_coverage_score": jurisdiction_quality,
            "case_intelligence_suggestion_count": modules.get("case_intelligence", {}).get("suggestion_count", 0),
            "key_insights": self._extract_key_insights(report),
        }

    def _extract_key_insights(self, report: Dict[str, Any]) -> List[str]:
        """提取关键洞察"""
        insights = []
        modules = report.get("modules", {})

        # 热点洞察
        hotspots = modules.get("hotspots", {}).get("hotspots", [])
        if hotspots:
            top_hotspot = hotspots[0]
            insights.append(f"最高风险区域集中了{top_hotspot.get('case_count', 0)}起案件")

        # 团伙洞察
        gangs = modules.get("gangs", {}).get("top_gangs", [])
        if gangs:
            total_gang_cases = sum(g.get("case_count", 0) for g in gangs)
            insights.append(f"识别到{len(gangs)}个相似条件组，涉及{total_gang_cases}起案件")

        # 时间模式洞察
        patterns = modules.get("patterns", {}).get("patterns", {})
        peak_hours = patterns.get("peak_hours", [])
        if peak_hours:
            hours = [str(h["hour"]) + "时" for h in peak_hours[:2]]
            insights.append(f"案件高发时段集中在{', '.join(hours)}")

        jurisdiction = modules.get("jurisdiction", {})
        coverage_score = jurisdiction.get("data_quality", {}).get("coverage_score")
        control_count = len(jurisdiction.get("patrol_plan", {}).get("control_points", []))
        if coverage_score is not None:
            insights.append(f"辖区底座完整度评分为{coverage_score}分")
        if control_count:
            insights.append(f"已形成{control_count}个防控参考点位")

        case_intelligence = modules.get("case_intelligence", {})
        for item in case_intelligence.get("insights", [])[:2]:
            insights.append(item)

        return insights

    def _generate_priority_actions(self, report: Dict[str, Any]) -> List[Dict[str, Any]]:
        """生成优先行动列表"""
        actions = []
        summary = report.get("summary", {})
        modules = report.get("modules", {})

        # 根据风险等级添加紧急行动
        risk_level = summary.get("overall_risk_level", "low")

        if risk_level in ["critical", "high"]:
            actions.append({
                "priority": 1,
                "action": "启动专题研判",
                "description": "当前风险等级较高，建议先形成案件复盘、相似条件和关注区域清单",
                "category": "analysis",
            })

        # 热点区域行动
        high_risk_hotspots = modules.get("hotspots", {}).get("high_risk_count", 0)
        if high_risk_hotspots > 0:
            actions.append({
                "priority": 2,
                "action": f"复盘{high_risk_hotspots}个高关注热点区域",
                "description": "将热点区域与历史案件、辖区底座和现场薄弱点交叉核验",
                "category": "area_attention",
            })

        # 团伙追踪行动
        high_risk_gangs = modules.get("gangs", {}).get("high_risk_gang_count", 0)
        if high_risk_gangs > 0:
            actions.append({
                "priority": 3,
                "action": f"复核{high_risk_gangs}个高关注条件组",
                "description": "重点比较共同时间、空间环境、车辆工具和现场薄弱点",
                "category": "condition_review",
            })

        jurisdiction = modules.get("jurisdiction", {})
        control_count = len(jurisdiction.get("patrol_plan", {}).get("control_points", []))
        if control_count:
            actions.append({
                "priority": 4,
                "action": f"形成{control_count}个辖区关注点位",
                "description": "将预防工作台控点纳入防控参考清单，由人工决定后续处置",
                "category": "jurisdiction",
            })
        coverage_score = jurisdiction.get("data_quality", {}).get("coverage_score")
        if isinstance(coverage_score, (int, float)) and coverage_score < 80:
            actions.append({
                "priority": 5,
                "action": "补齐业务资产和地图参考缺口",
                "description": "优先治理缺坐标、未校验和重复的井点、管线节点、技防点位；道路村屯走地图参考导入",
                "category": "jurisdiction",
            })

        return actions

    def _generate_recommendations(self, report: Dict[str, Any]) -> List[str]:
        """生成综合建议"""
        recommendations = []
        summary = report.get("summary", {})
        modules = report.get("modules", {})

        # 基于风险等级的建议
        risk_level = summary.get("overall_risk_level", "low")
        if risk_level == "critical":
            recommendations.append("建议立即组织专题研判，先形成相似条件、重点区域和现场短板清单")
        elif risk_level == "high":
            recommendations.append("建议在一周内完成专题复盘，制定针对性防控参考")

        # 基于热点的建议
        hotspots = modules.get("hotspots", {}).get("hotspots", [])
        if hotspots:
            recommendations.append(f"重点复盘{len(hotspots)}个热点区域，形成可解释的关注依据")

        # 基于团伙的建议
        gang_count = modules.get("gangs", {}).get("gang_count", 0)
        if gang_count > 0:
            recommendations.append(f"深入分析{gang_count}个相似条件组的作案条件和现场薄弱点")

        # 基于时间模式的建议
        patterns = modules.get("patterns", {}).get("patterns", {})
        peak_hours = patterns.get("peak_hours", [])
        if peak_hours:
            recommendations.append("根据发案时间规律调整重点关注时段，提高研判针对性")

        jurisdiction = modules.get("jurisdiction", {})
        data_quality = jurisdiction.get("data_quality", {})
        if data_quality.get("recommendations"):
            recommendations.extend(data_quality["recommendations"][:2])
        if jurisdiction.get("patrol_plan", {}).get("control_points"):
            recommendations.append("将辖区预防工作台生成的控点纳入防控参考清单，并按人工反馈修正相似条件权重")

        return recommendations
