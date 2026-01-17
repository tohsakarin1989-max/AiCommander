from app.ai.agents.base_agent import BaseAgent
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
"""
        elif self.specialty == "spatial":
            role_desc = """
你是一名【区域聚集分析专家】。
请从空间维度分析这些已破获案件/事件，重点识别：

1. **区域聚集特征**：
   - 哪些村屯/区域事件密集？
   - 事件是否沿特定道路/管线分布？
   - 是否存在明显的"热点区域"？

2. **上下游关联**：
   - 囤油点与盗油点的空间关系如何？
   - 查获车辆地点与其他事件的关联？
   - 是否能推断出作案团伙的活动范围？

3. **巡逻路线建议**：
   - 应重点巡逻哪些路口/路段？
   - 高风险区域周边5公里范围内还有哪些值得关注的点位？
   - 是否需要在特定村屯增设巡逻点？
"""
        elif self.specialty == "modus":
            role_desc = """
你是一名【作案手法分析专家】。
请从作案手法维度分析这些已破获案件/事件，重点提炼：

1. **作案模板提炼**：
   - 常见的作案手法有哪些（打孔、切割、偷接等）？
   - 常用的作案工具有哪些？
   - 作案团伙的典型组织结构？

2. **团伙特征识别**：
   - 多起事件是否可能属于同一团伙？（车辆相同/手法一致/区域重叠）
   - 专业化程度如何？是惯犯还是临时起意？
   - 是否存在"师傅带徒弟"的模仿作案？

3. **防范经验提炼**：
   - 针对常见手法，应如何加强巡逻识别？
   - 巡逻时应重点关注哪些可疑特征？
   - 哪些位置/设施类型最易被作案？
"""
        elif self.specialty == "prevention":
            role_desc = """
你是一名【防控建议专家】。
请综合所有信息，提出切实可行的巡逻防控建议：

1. **重点区域排查建议**：
   - 基于已有事件，哪些区域应优先排查？
   - 在高风险村屯周边，应重点寻找什么（隐蔽囤油点/可疑车辆/作案工具）？
   - 是否需要对特定区域进行地毯式排查？

2. **巡逻策略优化**：
   - 现有巡逻路线是否覆盖高风险区域？
   - 应在哪些时段/路口增加巡逻频次？
   - 建议采用何种巡逻方式（车巡/步巡/蹲守）？

3. **联防联控建议**：
   - 哪些区域需要与公安机关加强配合？
   - 是否需要发动群众线索举报？
   - 与周边单位的联防机制建议？
"""
        else:
            role_desc = """
你是一名【综合研判专家】。
请综合时间规律、空间分布、作案手法等多维度，对这些已破获案件/事件进行经验提炼。
重点关注：区域风险识别、规律总结、巡逻防控建议。
"""

        json_schema = """
请以JSON格式返回分析结果：
{
    "patterns": [
        {
            "type": "时间规律/空间规律/手法规律",
            "description": "规律描述",
            "evidence": "支撑该规律的事件列表"
        }
    ],
    "area_risks": [
        {
            "area_name": "村屯/区域名称",
            "risk_level": "high/medium/low",
            "reasons": ["风险原因1", "风险原因2"],
            "event_count": 3
        }
    ],
    "correlations": [
        {
            "events": ["事件1描述", "事件2描述"],
            "relation_type": "空间聚集/上下游关联/手法相似/车辆关联",
            "reasoning": "关联推理说明",
            "implication": "这意味着什么"
        }
    ],
    "patrol_suggestions": [
        {
            "location": "具体地点/路段",
            "reason": "为什么要关注这里",
            "timing": "建议巡逻时间",
            "focus_on": ["重点关注什么"]
        }
    ],
    "search_suggestions": [
        {
            "target": "排查目标（如：隐蔽囤油点）",
            "area": "排查区域",
            "method": "排查方法建议"
        }
    ],
    "experience_summary": "从这些案件中提炼的核心经验（1-2句话）"
}

注意：
- patterns 是从已有事件中识别的规律
- area_risks 是对区域风险的评估
- correlations 是事件之间可能的关联（需说明推理依据）
- patrol_suggestions 是具体可执行的巡逻建议
- search_suggestions 是排查重点建议
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
            try:
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                result = json.loads(content)
            except Exception:
                # 如果解析失败，返回原始内容
                result = {
                    "patterns": [],
                    "area_risks": [],
                    "correlations": [],
                    "patrol_suggestions": [],
                    "search_suggestions": [],
                    "experience_summary": "",
                    "raw_content": content,
                }

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
            try:
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                evaluation = json.loads(content)
            except:
                evaluation = {
                    "score": 5,
                    "strengths": [],
                    "weaknesses": [],
                    "suggestions": content
                }
            
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
作为研判委员会成员，请对以下匿名研判结果进行排名。

这些研判结果来自不同的分析专家，所有身份信息已被隐藏。
请基于以下标准进行客观评价：
1. **经验提炼深度**：是否从已破获案件中提炼出有价值的经验？
2. **规律识别准确性**：识别的时间/空间/手法规律是否有依据？
3. **区域风险评估**：风险评估是否合理、有针对性？
4. **巡逻建议可执行性**：巡逻建议是否具体、可操作？
5. **排查建议实用性**：排查建议是否能指导实际工作？

研判结果列表：
{analyses_text}

请提供以下内容（以JSON格式返回）：
{{
    "rankings": [
        {{
            "anonymous_id": "Response_1",
            "rank": 1,
            "score": 9,
            "reasoning": "为什么这个研判最好（如：规律识别准确，巡逻建议具体可执行）"
        }},
        {{
            "anonymous_id": "Response_2",
            "rank": 2,
            "score": 7,
            "reasoning": "为什么这个研判次之"
        }}
    ],
    "best_insights": ["从这些研判中提炼的最佳洞察1", "洞察2"],
    "overall_comment": "整体评价和综合建议"
}}

注意：
- rankings 数组应按排名从高到低排序（rank=1 表示最好）
- 每个排名必须包含 anonymous_id（对应上面的匿名标识）
- score 是1-10的评分
- best_insights 用于汇总各研判中的最佳发现
- 必须对所有研判结果进行排名，不能遗漏
"""
        
        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content
            
            # 尝试解析JSON
            try:
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                ranking_result = json.loads(content)
                
                # 验证排名结果格式
                if "rankings" not in ranking_result:
                    ranking_result["rankings"] = []
                    
            except Exception as e:
                # 如果解析失败，尝试从文本中提取排名信息
                ranking_result = {
                    "rankings": [],
                    "overall_comment": content,
                    "parse_error": str(e)
                }
            
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
            try:
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                optimized = json.loads(content)
            except:
                optimized = {
                    **original_analysis,
                    "optimized_content": content,
                    "version": original_analysis.get("version", 1) + 1
                }
            
            return optimized
        except Exception as e:
            return {
                **original_analysis,
                "error": str(e),
                "version": original_analysis.get("version", 1) + 1
            }

