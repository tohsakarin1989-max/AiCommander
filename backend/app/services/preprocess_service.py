from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.ai_model import AIModel
from app.ai.model_factory import ModelFactory
from app.config import settings
from app.utils.logger import logger


class CasePreprocessService:
    """
    案件预处理服务：
    - 对原始案情长文本做摘要
    - 抽取通用结构化特征（basic / modus / actors / oil / flow / risk / tags）
    - 结果写入 Case.features 字段，供后续圆桌研判和关联分析使用
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
    def _build_prompt(case: Case) -> str:
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
        }

        meta_text = "\n".join(
            f"- {k}: {v}"
            for k, v in meta.items()
            if v is not None
        )

        prompt = f"""
你是一名公安情报分析领域的专业助手，长期处理涉油案件。请对下面一条案件信息进行“通用、结构化”的预处理，并给出整体置信度。

【案件基础字段】（可能不完整，仅供参考）：
{meta_text}

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
  "modus": {{
    "target_object": "主要侵害对象/设施，如：输油管线/油罐车/加油站/居民住宅等",
    "modus_operandi": ["手法1", "手法2"],
    "tools": ["工具1", "工具2"],
    "time_pattern": ["主要作案时段/规律"],
    "weather_pattern": ["天气规律，如：大雾/无明显"]
  }},
  "actors": {{
    "facts": {{
      "known_roles": ["已确认角色1", "已确认角色2"],
      "known_vehicles": [
        {{
          "plate": "车牌号或未知",
          "type": "车辆类型",
          "suspected_fake_plate": false
        }}
      ]
    }},
    "clues": {{
      "possible_roles": ["可能存在的角色1", "可能存在的角色2"],
      "notes": "可以作为侦查抓手的线索，尚未证实"
    }},
    "hypotheses": {{
      "suspected_structure": "可能存在的团伙结构和分工，需侦查验证"
    }}
  }},
  "oil": {{
    "facts": {{
      "oil_type": "如：汽油/柴油/原油/润滑油/非涉油则为null",
      "volume": 0,
      "value": 0,
      "facility_type": "目标设施类型",
      "facility_owner": "设施所属单位"
    }},
    "clues": {{
      "scene_observations": ["现场可见油迹/容器等可供研判的线索"]
    }},
    "hypotheses": {{
      "possible_risk": "基于多案共性推测的风险点，需进一步核查"
    }}
  }},
  "flow": {{
    "upstream_source": "上游来源点（如某段管线某号桩/某站某枪），无则null",
    "downstream_destination": ["疑似销赃去向1", "疑似销赃去向2"],
    "economic_impact": "经济影响程度：特别重大/重大/一般/较小"
  }},
  "risk": {{
    "level": "高风险/中风险/低风险",
    "factors": ["风险因素1", "风险因素2"]
  }},
  "tags": ["简要标签1", "简要标签2"],
  "confidence": 0.0
}}

注意：
1. 只输出 JSON，不要包含任何解释性文字；
2. "confidence" 为本次整体结构化结果的置信度（0~1），当你对整体判断较不确定时请给出较低分（如 0.3~0.6）；
3. 如果信息缺失，请保持字段但填 null 或空数组；
4. 字段名必须与模板完全一致。
"""
        return prompt

    @staticmethod
    def preprocess_case(db: Session, case_id: int) -> Optional[Dict[str, Any]]:
        """
        同步预处理指定案件：
        - 如果缺少 OPENAI_API_KEY，则直接返回 None
        - 成功时更新 Case.features 字段并返回结构化结果
        """
        llm = CasePreprocessService._build_llm(db)
        if llm is None:
            return None

        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            logger.warning(f"预处理失败，案件 {case_id} 不存在")
            return None

        prompt = CasePreprocessService._build_prompt(case)
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
            return None

        # 将结果写入 Case.features（保留原有内容）
        features = case.features or {}
        features.update(data)
        case.features = features
        db.commit()
        db.refresh(case)
        logger.info(f"案件 {case_id} 预处理完成并写入 features")
        return data


import json  # 放在文件末尾，避免与上方注释混淆


