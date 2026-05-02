from app.ai.agents.base_agent import BaseAgent
from app.ai.utils import parse_llm_json_response
from typing import Dict, List, Optional
import json


class AnalystAgent(BaseAgent):
    """
    分析员智能体（经验提取与巡逻指导导向）

    核心定位：从已破获案件中提炼经验，识别区域风险，指导巡逻防控

    specialty 用于专家角色化：
    - temporal: 时间规律专家 - 分析发案时间规律，识别周期性特征
    - spatial: 区域聚集专家 - 分析空间分布，识别高风险区域和活动范围
    - modus: 作案手法专家 - 提炼作案模板，识别团伙特征和上下游关联
    - prevention: 防控建议专家 - 专注巡逻路线规划和预防措施建议
    - None: 综合分析员

    注意：本系统仅录入已破获案件信息，不涉及在侦线索。
    分析目标是提炼经验、识别规律、指导巡逻，而非追查嫌疑人。
    """

    def __init__(self, model, llm, specialty: Optional[str] = None):
        super().__init__(model, llm)
        self.specialty = specialty or model.config.get("specialty") if getattr(model, "config", None) else None

    async def process(self, input_data: dict) -> dict:
        """实现抽象方法，处理输入并返回结果"""
        # AnalystAgent 主要通过 analyze_cases, rank_analyses 等方法工作
        # 这里提供一个通用的 process 实现
        if "case_information" in input_data:
            result = await self.analyze_cases(input_data["case_information"])
            return result
        elif "anonymous_analyses" in input_data:
            result = await self.rank_analyses(input_data["anonymous_analyses"])
            return result
        elif "anonymous_analysis" in input_data:
            result = await self.evaluate_analysis(input_data["anonymous_analysis"])
            return result
        elif "original_analysis" in input_data and "feedbacks" in input_data:
            result = await self.optimize_analysis(
                input_data["original_analysis"],
                input_data["feedbacks"]
            )
            return result
        else:
            return {"error": "Unknown input format"}

    def _build_analysis_prompt(self, case_information: str) -> str:
        """
        根据专家角色构建分析提示

        核心目标：从已破获案件中提炼经验，识别区域风险规律，指导巡逻防控
        """
        base_intro = """
【重要说明】
以下是已经破获的涉油案件/事件信息。这些都是已结案的历史数据，用于经验提炼和规律识别。
你的分析目标是：识别规律 → 评估区域风险 → 指导未来巡逻防控。
请勿尝试追查嫌疑人或提供侦查建议，聚焦于经验提炼和巡逻指导。

【事件/案件信息】
""" + case_information

        if self.specialty == "temporal":
            role_desc = """
你是一名【时间规律分析专家】。
请从时间维度分析这些已破获案件/事件，重点识别：

1. **周期性规律**：
   - 是否存在特定月份/季节的发案高峰？
   - 是否存在特定星期几或时段的规律？
   - 作案时间是否与农忙/农闲、节假日相关？

2. **时间间隔分析**：
   - 同一区域内事件的时间间隔是怎样的？
   - 间隔是否有规律（如每隔2-3个月）？

3. **巡逻时间建议**：
   - 基于时间规律，应在哪些时段加强巡逻？
   - 是否需要增加夜间/凌晨巡逻频次？

【输出要求】
- patterns：最多3条，按置信度排序
- patrol_suggestions：最多3条，必须包含具体时段（如"周三凌晨02:00-04:00"）
- experience_summary：用一句话概括时间规律特征，格式："本区域案件集中于[时段]，与[原因]相关"
"""
        elif self.specialty == "spatial":
            role_desc = """
你是一名【区域聚集分析专家】。
请从空间维度分析这些已破获案件/事件，重点识别：

1. **区域聚集特征**：
   - 哪些村屯/区域事件密集？
   - 事件是否沿特定道路/输油管线（干线/集输支线）分布？
   - 哪些输油设施（油库、储油罐区、加油站）周边案件集中？
   - 是否存在明显的"热点区域"？

2. **上下游关联**：
   - 囤油点与盗油点的空间关系如何？
   - 查获罐车地点与管线盗油点的关联？
   - 是否能推断出作案团伙的活动范围（管线沿线半径内）？

3. **巡逻路线建议**：
   - 应重点巡逻哪些管线路口/路段？
   - 高风险输油设施周边5公里范围内还有哪些值得关注的点位？
   - 是否需要在特定村屯或管线阀室增设巡逻点？

【输出要求】
- area_risks：最多5个区域，必须包含经纬度描述（如"某某村东侧500m管线段"）
- correlations：重点关注上下游关联（囤油点←→盗油点），最多3条
- experience_summary：用一句话概括空间规律，格式："案件集中于[区域/管线段]，[上下游/聚集]特征明显"
"""
        elif self.specialty == "modus":
            role_desc = """
你是一名【作案手法分析专家】。
请从作案手法维度分析这些已破获案件/事件，重点提炼：

1. **作案模板提炼**：
   常见涉油作案手法包括（请结合实际案件识别）：
   - 打孔盗油：在输油管线上钻孔，使用软管和泵抽取油品
   - 切割管线：截断管段直接取油
   - 偷接管线：非法接驳分支管道长期盗取
   - 罐车过驳：用罐车在隐蔽地点装载盗取油品
   - 混入合法装运：伪造运输单据掩盖非法油品
   - 常用作案工具：电钻、割管机、手摇泵、储油桶、罐车

2. **团伙特征识别**：
   - 多起事件是否可能属于同一团伙？（车牌相同/手法一致/区域重叠）
   - 专业化程度：惯犯（工具专业、路线固定）还是临时起意？
   - 是否存在"师傅带徒弟"的模仿作案或团伙分工？

3. **防范经验提炼**：
   - 针对打孔/偷接等常见手法，巡逻时应关注哪些可疑特征？
   - 哪些类型的设施（阀室/弯管/偏僻管线段）最易被作案？
   - 罐车查扣时应重点核查哪些信息（运输单据、油品来源证明）？

【输出要求】
- patterns：按手法类型分类（每种手法最多1条pattern）
- correlations：必须尝试识别是否存在"师傅带徒弟"或分工型团伙（如：专人打孔+专人运输）
- experience_summary：用一句话概括手法特征，格式："主要手法为[手法]，惯犯特征为[特征]，需重点查扣[对象]"
"""
        elif self.specialty == "prevention":
            role_desc = """
你是一名【防控建议专家】。
请综合所有信息，提出切实可行的巡逻防控建议：

1. **重点区域排查建议**：
   - 基于已有事件，哪些区域应优先排查？
   - 在高风险村屯周边及管线沿线，应重点寻找什么？
     （隐蔽囤油点/可疑罐车/打孔痕迹/临时接管设施）
   - 是否需要对特定管线段进行地毯式排查？

2. **巡逻策略优化**：
   - 现有巡逻路线是否覆盖高风险管线段和油库周边？
   - 应在哪些时段/路口增加巡逻频次（重点关注夜间罐车动向）？
   - 建议采用何种巡逻方式（车巡/步巡/管线徒步检查/无人机巡检）？

3. **联防联控建议**：
   - 应与哪些单位加强配合？
     · 公安机关（交警查扣过路罐车）
     · 管道公司/油田保卫部门（共享管线告警数据）
     · 周边加油站（核查可疑购油行为）
   - 是否需要发动群众线索举报（油品异味/可疑车辆/地面油污）？
   - 是否建议暂时提升该管线段的巡检频次？

【输出要求】
- patrol_suggestions：必须包含4种巡逻方式（车巡/步巡/管线检查/无人机）中至少2种，说明各自适用场景
- search_suggestions：必须区分"主动排查目标"（设施）和"线索线索举报"（群众反映），最多4条
- experience_summary：用一句话总结防控重点，格式："防控重点为[区域/时段]，应[联防联控措施]"
"""
        else:
            role_desc = """
你是一名【油品供应链溯源专家】。
请从涉油犯罪的完整供应链角度分析这些已破获案件，重点识别：

1. **盗取环节**：
   - 盗油发生在哪些设施/管线段？（输油管线/油库/加油站/油罐车）
   - 主要使用哪种方式？（打孔/切割/非法接驳/其他）
   - 盗油规模：单次数量、频率、总量估算

2. **囤积/转运环节**：
   - 盗取后油品去向推断：是否有隐蔽囤积点？
   - 查获的罐车/储油桶与哪些盗油地点空间关联？
   - 转运路线推断：多起案件是否共享同一转运路径？

3. **销售环节**（如有线索）：
   - 是否有油品流向特定加油站/炼化企业的迹象？
   - 非法油品是否通过伪造单据混入合法渠道？

4. **链条完整性评估**：
   - 已破获案件覆盖了供应链的哪几个环节？
   - 哪个环节证据最薄弱？（对未来巡逻有指导价值）
   - 整条链条中，最易被巡逻截断的关键节点是哪里？

【输出要求】
- correlations：必须尝试构建"盗取点→囤积点→转运路线"的空间关联链，最多2条链
- patterns：聚焦供应链规律（而非单一案件），最多3条
- search_suggestions：建议从链条下游（销售端）倒查，最多3条
- experience_summary：用一句话总结供应链特征，格式："涉案供应链以[环节]为主，[关键薄弱点]是巡逻截断的最佳介入点"
"""

        json_schema = """
请以JSON格式返回分析结果（严格遵守数量限制）：
{
    "patterns": [
        {
            "type": "时间规律/空间规律/手法规律/供应链规律",
            "description": "规律描述（一句话，含具体数据或地名）",
            "evidence": ["支撑证据1（案件编号+关键特征）", "证据2"],
            "confidence": "high/medium/low"
        }
    ],
    "area_risks": [
        {
            "area_name": "村屯/管线段/设施名称",
            "risk_level": "high/medium/low",
            "reasons": ["原因1（含具体特征）", "原因2"],
            "event_count": 3,
            "recommended_action": "建议采取的具体行动（一句话）"
        }
    ],
    "correlations": [
        {
            "events": ["事件编号1", "事件编号2"],
            "relation_type": "上下游关联/手法相似/车辆关联/人员关联/时空聚集",
            "reasoning": "关联推理（含具体证据，非主观猜测）",
            "implication": "对巡逻防控的意义",
            "confidence": "high/medium/low"
        }
    ],
    "patrol_suggestions": [
        {
            "location": "具体地点/路段/管线桩号",
            "reason": "为什么重点关注（一句话）",
            "timing": "具体时段（如：周三/五 22:00-02:00）",
            "focus_on": ["重点查什么（具体化）"],
            "method": "车巡/步巡/管线检查/无人机",
            "priority": "P0/P1/P2"
        }
    ],
    "search_suggestions": [
        {
            "target": "排查目标（具体化，如：2km范围内废弃院落/沿路罐车）",
            "area": "排查区域（含地标参照）",
            "method": "排查方法（具体操作步骤）",
            "expected_find": "预期发现什么"
        }
    ],
    "experience_summary": "核心经验（一句话，格式见角色说明中的【输出要求】）"
}

数量限制：patterns≤3，area_risks≤5，correlations≤3，patrol_suggestions≤4，search_suggestions≤3
注意：所有字段必须基于案件事实，禁止凭空推断无依据的关联。
"""

        return f"{role_desc}\n{base_intro}\n\n{json_schema}"

    async def analyze_cases(self, case_information: str) -> Dict:
        """
        分析已破获案件/事件，提炼经验并给出巡逻建议

        返回格式包含：patterns, area_risks, correlations, patrol_suggestions, search_suggestions
        """
        prompt = self._build_analysis_prompt(case_information)

        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content

            # 尝试解析JSON
            default_result = {
                "patterns": [],
                "area_risks": [],
                "correlations": [],
                "patrol_suggestions": [],
                "search_suggestions": [],
                "experience_summary": "",
                "raw_content": content,
            }
            result, error = parse_llm_json_response(content, default_result)
            if error:
                result["parse_error"] = error

            return result
        except Exception as e:
            return {
                "patterns": [],
                "area_risks": [],
                "correlations": [],
                "patrol_suggestions": [],
                "search_suggestions": [],
                "experience_summary": f"分析出错: {str(e)}",
                "error": str(e),
            }
    
    async def evaluate_analysis(self, anonymous_analysis: Dict) -> Dict:
        """评价其他分析员的研判结果（从经验提炼和巡逻指导价值角度）"""
        analysis_text = json.dumps(anonymous_analysis, ensure_ascii=False, indent=2)

        prompt = f"""
请评价以下匿名研判结果（满分10分）：

{analysis_text}

评价标准（经验提炼与巡逻指导导向）：
1. 规律识别是否准确、有依据？
2. 区域风险评估是否合理？
3. 事件关联分析是否有洞察力？
4. 巡逻建议是否具体、可执行？
5. 排查建议是否有针对性？

请提供以下内容（以JSON格式返回）：
{{
    "score": 8,
    "strengths": ["优点1（如：规律识别准确）", "优点2", "优点3"],
    "weaknesses": ["不足1（如：巡逻建议不够具体）", "不足2"],
    "suggestions": "改进建议（如何使分析更具指导价值）"
}}
"""
        
        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content
            
            # 尝试解析JSON
            default_eval = {
                "score": 5,
                "strengths": [],
                "weaknesses": [],
                "suggestions": content
            }
            evaluation, _ = parse_llm_json_response(content, default_eval)

            return evaluation
        except Exception as e:
            return {
                "score": 5,
                "strengths": [],
                "weaknesses": [str(e)],
                "suggestions": "评价时出错"
            }
    
    async def rank_analyses(self, anonymous_analyses: List[Dict]) -> Dict:
        """
        对多个匿名研判结果进行排名
        评价标准：经验提炼深度、规律识别准确性、巡逻建议可执行性
        """
        analyses_text = "\n\n".join([
            f"研判结果 {i+1}（匿名标识：{analysis.get('_anonymous_id', f'Response_{i+1}')}）：\n"
            f"{json.dumps(analysis, ensure_ascii=False, indent=2)}"
            for i, analysis in enumerate(anonymous_analyses)
        ])

        prompt = f"""
作为研判委员会成员，请对以下匿名研判结果进行客观评分排名。

【评分量表】（总分10分，按各维度求和）
1. 规律识别质量（0-3分）
   - 3分：规律有具体数据支撑（如"周三凌晨2-4时，占总案件35%"）
   - 2分：规律有案件事实依据但缺乏量化
   - 1分：规律描述过于笼统
   - 0分：规律纯属推断无依据

2. 巡逻建议可执行性（0-3分）
   - 3分：包含具体地点+时段+巡逻方式+重点查什么
   - 2分：包含地点和时段但方式不具体
   - 1分：只有方向性建议
   - 0分：完全无法执行

3. 关联分析深度（0-2分）
   - 2分：识别到上下游关联或人员/车辆关联
   - 1分：识别到一般时空关联
   - 0分：无关联分析

4. 专业性（0-2分）
   - 2分：使用涉油专业术语（打孔/偷接/囤油点/阀室等），分析符合涉油犯罪规律
   - 1分：有一定专业性但较泛化
   - 0分：无专业特征

研判结果列表：
{analyses_text}

请提供（以JSON格式返回）：
{{
    "rankings": [
        {{
            "anonymous_id": "Response_1",
            "rank": 1,
            "score": 8,
            "score_breakdown": {{"规律识别": 3, "可执行性": 2, "关联深度": 2, "专业性": 1}},
            "reasoning": "最突出的优点（一句话）+ 主要不足（一句话）"
        }}
    ],
    "best_insights": ["从所有研判中提炼的最有价值发现（≤3条，具体化）"],
    "overall_comment": "整体质量评价（1-2句话）"
}}

注意：rankings 必须包含所有研判，按 rank 从小到大排序。
"""
        
        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content
            
            # 尝试解析JSON
            default_ranking = {
                "rankings": [],
                "overall_comment": content,
            }
            ranking_result, error = parse_llm_json_response(content, default_ranking)

            # 验证排名结果格式
            if "rankings" not in ranking_result:
                ranking_result["rankings"] = []
            if error:
                ranking_result["parse_error"] = error

            return ranking_result
        except Exception as e:
            return {
                "rankings": [],
                "overall_comment": f"排名时出错: {str(e)}",
                "error": str(e)
            }
    
    async def optimize_analysis(
        self,
        original_analysis: Dict,
        feedbacks: List[Dict]
    ) -> Dict:
        """基于反馈优化分析结果"""
        feedback_text = "\n".join([
            f"反馈 {i+1}：\n"
            f"  评分：{f.get('score', 'N/A')}\n"
            f"  优点：{', '.join(f.get('strengths', []))}\n"
            f"  不足：{', '.join(f.get('weaknesses', []))}\n"
            f"  建议：{f.get('suggestions', '')}"
            for i, f in enumerate(feedbacks)
        ])
        
        original_text = json.dumps(original_analysis, ensure_ascii=False, indent=2)
        
        prompt = f"""
基于以下反馈，请优化你的分析结果：

原始分析：
{original_text}

反馈意见：
{feedback_text}

请生成优化后的分析结果（以JSON格式返回，格式与原始分析相同）。
"""
        
        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content
            
            # 尝试解析JSON
            default_optimized = {
                **original_analysis,
                "optimized_content": content,
                "version": original_analysis.get("version", 1) + 1
            }
            optimized, _ = parse_llm_json_response(content, default_optimized)

            return optimized
        except Exception as e:
            return {
                **original_analysis,
                "error": str(e),
                "version": original_analysis.get("version", 1) + 1
            }

