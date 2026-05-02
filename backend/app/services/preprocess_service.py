import json
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.ai_model import AIModel
from app.ai.model_factory import ModelFactory
from app.config import settings
from app.services.case_quality_service import CaseQualityService
from app.utils.logger import logger


class CasePreprocessService:
    """
    案件预处理服务：
    - 对原始案情长文本做摘要
    - 抽取事实、现场条件、可解释推断、信息缺口和防控参考
    - 结果写入 Case.features 字段，供后续相似条件研判、复盘和报告使用
    """

    @staticmethod
    def _build_llm(db: Session):
        """
        使用与主持人一致的 LLM：
        - 优先选择 role=moderator 且 is_default=true 的模型
        - 若无默认主持人，则选择任意一个主持人模型
        """
        factory = ModelFactory()
        query = db.query(AIModel).filter(AIModel.role == "moderator", AIModel.is_active == True)
        default_model = query.filter(AIModel.is_default == True).first()
        model = default_model or query.first()
        if not model:
            logger.warning("未找到主持人模型，无法进行案件预处理")
            return None
        try:
            return factory.create_llm(model)
        except Exception as e:
            logger.error(f"使用主持人模型创建LLM失败: {e}")
            return None

    @staticmethod
    def _build_prompt(db: Session, case: Case) -> str:
        """
        构造提示词，要求大模型输出统一 schema 的 JSON。
        """
        raw_text = case.description or ""
        meta = {
            "case_number": case.case_number,
            "occurred_time": str(case.occurred_time) if case.occurred_time else None,
            "location": case.location,
            "latitude": case.latitude,
            "longitude": case.longitude,
            "case_type": case.case_type,
            "report_time": str(case.report_time) if case.report_time else None,
            "report_unit": case.report_unit,
            "source_type": case.source_type,
            "oil_nature": case.oil_nature,
            "water_cut": case.water_cut,
            "police_reported": case.police_reported,
            "case_filed": case.case_filed,
        }
        profile = CaseQualityService.build_case_feature_profile(db, case)
        profile_text = json.dumps(profile, ensure_ascii=False, default=str)

        meta_text = "\n".join(
            f"- {k}: {v}"
            for k, v in meta.items()
            if v is not None
        )

        prompt = f"""
你是一名涉油案件研判辅助助手。请对下面一条已侦破/已处置案件信息进行结构化预处理，目标是帮助人员复盘经验、发现相似条件和形成防控参考，而不是预测犯罪或直接派发任务。

【案件基础字段】（可能不完整，仅供参考）：
{meta_text}

【标准化案件画像】（来自案件台账、车辆/人员/证据/质量评分，请优先使用其中的事实字段）：
{profile_text}

【原始案情描述】：
{raw_text}

请将综合分析结果以【严格合法的 JSON】格式返回，字段结构如下（没有信息的字段请给 null 或空数组，不要修改字段名）：

{{
  "basic": {{
    "title": "不超过30字的简短案名",
    "summary": "200~400字的标准化案情摘要，去除无关细节",
    "case_type": "案件类型，如：涉油盗窃/普通盗窃/诈骗等",
    "time": "标准化后的主要发生时间，ISO字符串或简明描述",
    "location": "标准化地点（包含关键信息即可）"
  }},
  "geo": {{
    "latitude": {{"type": "number or null"}},
    "longitude": {{"type": "number or null"}},
    "region": "行政区/辖区名称",
    "place_type": "地点类型，如：居民区/管线附近/工地/服务区/油库等"
  }},
  "facts": {{
    "persons": ["已确认人员事实，必须来自字段或描述"],
    "vehicles": [
      {{
        "plate": "车牌号或未知",
        "type": "车辆类型",
        "source": "字段/描述/未知"
      }}
    ],
    "oil": {{
      "oil_type": "油品类型",
      "oil_nature": "油品性质",
      "volume": 0,
      "value": 0,
      "water_cut": 0
    }},
    "evidence": ["证据或现场记录事实"],
    "source": "发现来源/报送来源"
  }},
  "scene_conditions": {{
    "target_object": "主要侵害对象/设施",
    "place_type": "井口/管线/站库/道路/村屯周边/其他",
    "road_access": ["道路通达、便道、路口等事实或待核实项"],
    "nearby_environment": ["村屯、井区、管线、站库、空旷地等环境特征"],
    "monitoring_status": "技防/照明/监控情况；未知则写待核实",
    "weak_points": ["现场薄弱点或可复盘条件，必须说明依据"]
  }},
  "modus": {{
    "target_object": "主要侵害对象/设施，如：输油管线/油罐车/加油站/居民住宅等",
    "modus_operandi": ["手法1", "手法2"],
    "tools": ["工具1", "工具2"],
    "time_pattern": ["主要作案时段/规律"],
    "weather_pattern": ["天气规律，如：大雾/无明显"]
  }},
  "inferences": [
    {{
      "claim": "基于事实得出的模式或风险条件推断",
      "basis": ["支撑该推断的字段、案情片段或质量画像"],
      "confidence": 0.0,
      "needs_verification": true
    }}
  ],
  "risk": {{
    "level": "高风险/中风险/低风险",
    "factors": ["风险因素1", "风险因素2"]
  }},
  "recommendations": [
    {{
      "action": "防控参考或信息补齐建议，不得写成已派发任务",
      "basis": ["建议依据"],
      "priority": "high/medium/low",
      "boundary": "仅供人工研判和防控参考"
    }}
  ],
  "management": {{
    "report_quality_score": 0,
    "report_quality_level": "high/medium/low",
    "missing_fields": ["缺失字段1"],
    "timeliness": {{
      "reported_within_1h": true,
      "entered_within_48h": true
    }},
    "recommended_completion_actions": ["补齐动作1"]
  }},
  "analysis_readiness": {{
    "spacetime": "ready/partial/missing_geo",
    "similarity": "ready/partial/missing_features",
    "scene": "ready/partial/missing_scene",
    "area_profile": "ready/partial/missing_geo",
    "prevention_reference": "ready/partial/missing_basis"
  }},
  "tags": ["简要标签1", "简要标签2"],
  "confidence": 0.0
}}

注意：
1. 只输出 JSON，不要包含任何解释性文字；
2. "confidence" 为本次整体结构化结果的置信度（0~1），当你对整体判断较不确定时请给出较低分（如 0.3~0.6）；
3. 如果信息缺失，请保持字段但填 null 或空数组；
4. 字段名必须与模板完全一致；
5. 不要输出“团伙结构”“完整销赃链条”“巡逻派发”“圆桌会议任务”等当前数据无法稳定支撑的结论；
6. 对推断和建议必须写明 basis，无法证明的内容放入 needs_verification。
"""
        return prompt

    @staticmethod
    def _build_deterministic_features(db: Session, case: Case) -> Dict[str, Any]:
        profile = CaseQualityService.build_case_feature_profile(db, case)
        quality = profile["quality"]
        readiness = {
            key: value["status"]
            for key, value in profile["analysis_readiness"].items()
        }
        vehicles = profile["vehicles"] or profile["legacy_vehicle_info"]
        persons = profile["actors"]["persons"] or profile["actors"]["legacy_persons"]
        vehicle_items = []
        for vehicle in vehicles:
            if not isinstance(vehicle, dict):
                continue
            plate = vehicle.get("plate_number") or vehicle.get("plate") or "未知"
            vehicle_items.append({
                "plate": plate,
                "type": vehicle.get("vehicle_type") or vehicle.get("type"),
                "suspected_fake_plate": bool(vehicle.get("suspected_fake_plate", False)),
            })
        known_roles = []
        for person in persons:
            if isinstance(person, dict):
                role = person.get("role") or person.get("handling_status") or person.get("name")
                if role:
                    known_roles.append(str(role))

        risk_factors = []
        if quality["level"] == "low":
            risk_factors.append("案件信息缺项较多，研判置信度受限")
        if case.oil_volume and case.oil_volume >= 1:
            risk_factors.append("涉案油量较大")
        if profile["quality"]["facts"].get("reported_within_1h") is False:
            risk_factors.append("报送超出 1 小时要求")
        if profile["quality"]["facts"].get("has_vehicle_signal"):
            risk_factors.append("存在车辆转运或车辆线索")

        downstream = case.downstream_destination
        downstream_list = [downstream] if isinstance(downstream, str) and downstream else []

        tags = [
            item
            for item in (
                case.case_type,
                case.source_type,
                case.oil_nature,
                case.report_unit,
                case.modus_operandi,
            )
            if item
        ]
        scene_observations = [
            text
            for text in (case.source_detail, case.oil_handling)
            if text
        ]
        readiness_v2 = {
            "spacetime": readiness.get("spacetime", "partial"),
            "similarity": "ready" if len(tags) >= 2 else "partial",
            "scene": "ready" if (case.location and (case.facility_type or scene_observations)) else "partial",
            "area_profile": "ready" if (case.latitude is not None and case.longitude is not None) else "missing_geo",
            "prevention_reference": "ready" if risk_factors else "partial",
        }
        recommendations = []
        if quality.get("recommendations"):
            recommendations.append({
                "action": "补齐案件信息后再生成高置信度研判",
                "basis": quality.get("recommendations", [])[:3],
                "priority": "high" if quality["level"] == "low" else "medium",
                "boundary": "仅供人工研判和防控参考",
            })
        if case.latitude is None or case.longitude is None:
            recommendations.append({
                "action": "补齐案发坐标以关联道路、村屯、井口和数智自动化事件",
                "basis": ["案件缺少经纬度"],
                "priority": "high",
                "boundary": "仅供人工研判和防控参考",
            })
        if profile["quality"]["facts"].get("has_vehicle_signal"):
            recommendations.append({
                "action": "复盘车辆类型、停留位置和道路通达条件",
                "basis": ["案件存在车辆转运或车辆线索"],
                "priority": "medium",
                "boundary": "仅供人工研判和防控参考",
            })

        return {
            "preprocess_mode": "deterministic_fallback",
            "basic": {
                "title": f"{case.case_type or '案件'}-{case.case_number}",
                "summary": case.description or "暂无案情描述",
                "case_type": case.case_type,
                "time": case.occurred_time.isoformat() if case.occurred_time else None,
                "location": case.location,
            },
            "geo": {
                "latitude": case.latitude,
                "longitude": case.longitude,
                "region": case.report_unit,
                "place_type": case.facility_type,
            },
            "facts": {
                "persons": known_roles,
                "vehicles": [
                    {
                        "plate": vehicle.get("plate"),
                        "type": vehicle.get("type"),
                        "source": "案件车辆字段",
                    }
                    for vehicle in vehicle_items
                ],
                "oil": {
                    "oil_type": case.oil_type,
                    "oil_nature": case.oil_nature,
                    "volume": case.oil_volume,
                    "value": case.oil_value,
                    "water_cut": case.water_cut,
                },
                "evidence": scene_observations,
                "source": case.source_type,
            },
            "scene_conditions": {
                "target_object": case.facility_type,
                "place_type": case.facility_type,
                "road_access": [],
                "nearby_environment": [case.location] if case.location else [],
                "monitoring_status": "技防/照明/监控情况待核实",
                "weak_points": risk_factors,
            },
            "modus": {
                "target_object": case.facility_type,
                "modus_operandi": [case.modus_operandi] if case.modus_operandi else [],
                "tools": [],
                "time_pattern": [f"{case.occurred_time.hour:02d}:00"] if case.occurred_time else [],
                "weather_pattern": [],
            },
            "actors": {
                "facts": {
                    "known_roles": known_roles,
                    "known_vehicles": vehicle_items,
                },
                "clues": {
                    "possible_roles": [],
                    "notes": case.person_handling,
                },
                "hypotheses": {
                    "suspected_structure": "当前预处理不做团伙结构推断，人员关系仅以已掌握事实为准",
                },
            },
            "oil": {
                "facts": {
                    "oil_type": case.oil_type,
                    "oil_nature": case.oil_nature,
                    "volume": case.oil_volume,
                    "value": case.oil_value,
                    "water_cut": case.water_cut,
                    "facility_type": case.facility_type,
                    "facility_owner": case.facility_owner,
                },
                "clues": {
                    "scene_observations": [
                        text
                        for text in (case.source_detail, case.oil_handling)
                        if text
                    ],
                },
                "hypotheses": {
                    "possible_risk": "涉油案件需结合已掌握事实核查油品来源、去向线索和现场条件"
                    if profile["quality"]["facts"].get("has_oil_signal")
                    else None,
                },
            },
            "flow": {
                "upstream_source": case.upstream_source,
                "downstream_destination": downstream_list,
                "economic_impact": "重大" if (case.oil_value or 0) >= 100000 else "一般",
            },
            "inferences": [
                {
                    "claim": factor,
                    "basis": ["案件质量画像", "案件结构化字段"],
                    "confidence": round(max(0.35, min(0.75, quality["score"] / 100)), 2),
                    "needs_verification": quality["level"] != "high",
                }
                for factor in risk_factors
            ],
            "risk": {
                "level": "高风险" if quality["level"] == "low" else "中风险" if quality["level"] == "medium" else "低风险",
                "factors": risk_factors,
            },
            "recommendations": recommendations,
            "management": {
                "report_quality_score": quality["score"],
                "report_quality_level": quality["level"],
                "missing_fields": [
                    item["label"]
                    for item in quality.get("missing_required", [])
                    if isinstance(item, dict)
                ],
                "timeliness": {
                    "reported_within_1h": quality["facts"].get("reported_within_1h"),
                    "entered_within_48h": quality["facts"].get("entered_within_48h"),
                },
                "recommended_completion_actions": quality.get("recommendations", []),
            },
            "analysis_readiness": readiness_v2,
            "legacy_analysis_readiness": readiness,
            "tags": list(dict.fromkeys(tags)),
            "confidence": round(max(0.35, min(0.85, quality["score"] / 100)), 2),
        }

    @staticmethod
    def _write_features(db: Session, case: Case, data: Dict[str, Any]) -> Dict[str, Any]:
        features = case.features or {}
        features.update(data)
        case.features = features
        db.commit()
        db.refresh(case)
        return data

    @staticmethod
    def preprocess_case(db: Session, case_id: int) -> Optional[Dict[str, Any]]:
        """
        同步预处理指定案件：
        - 如果没有可用 LLM，则回退到案件画像的确定性预处理
        - 成功时更新 Case.features 字段并返回结构化结果
        """
        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            logger.warning(f"预处理失败，案件 {case_id} 不存在")
            return None

        llm = CasePreprocessService._build_llm(db)
        if llm is None:
            data = CasePreprocessService._build_deterministic_features(db, case)
            logger.info(f"案件 {case_id} 使用确定性预处理结果写入 features")
            return CasePreprocessService._write_features(db, case, data)

        prompt = CasePreprocessService._build_prompt(db, case)
        try:
            resp = llm.invoke(prompt)
            content = resp.content
            # 兼容模型输出 ```json ... ``` 包裹的情况
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            data = json.loads(content)  # type: ignore[name-defined]
        except Exception as e:
            logger.error(f"案件 {case_id} 预处理JSON解析失败: {e}")
            data = CasePreprocessService._build_deterministic_features(db, case)

        logger.info(f"案件 {case_id} 预处理完成并写入 features")
        return CasePreprocessService._write_features(db, case, data)
