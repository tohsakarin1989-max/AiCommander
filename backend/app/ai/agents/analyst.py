from app.ai.agents.base_agent import BaseAgent
from typing import Dict, List, Optional
import json


class AnalystAgent(BaseAgent):
    """
    分析员智能体
    specialty 用于专家角色化：
    - spatial: 空间/设施安全专家
    - modus: 作案手法/团伙结构专家
    - flow: 油品流向/经济链条专家
    - None: 通用分析员
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
        """根据专家角色构建不同分析提示"""
        base_intro = "以下是近期涉油及相关案件的汇总信息：\n\n" + case_information

        if self.specialty == "spatial":
            role_desc = """
你是一名【空间与设施安全专家】。
重点从以下角度进行分析：
1. 结合经纬度、地点、目标设施类型（管线/油库/加油站/油罐车等），识别高风险区域、串案带、重点桩号/路段；
2. 分析安防薄弱点（监控盲区、周界、防护措施缺失），评估再次发生案件的可能性；
3. 对巡逻路线、重点布控点和设施加固提出具体建议。
"""
        elif self.specialty == "modus":
            role_desc = """
你是一名【作案手法与团伙结构专家】。
重点从以下角度进行分析：
1. 提炼每起案件的“作案模板”（目标对象 + 作案手法 + 工具 + 时间/天气规律）；
2. 判断是否存在同一团伙或模仿作案（固定车辆、固定时段、固定破拆方式等）；
3. 评估作案专业化程度，并提出针对性的侦查方向和防控建议。
"""
        elif self.specialty == "flow":
            role_desc = """
你是一名【油品流向与经济链条专家】。
重点从以下角度进行分析：
1. 结合油品类型、数量、价值以及上游来源点，梳理油品被盗/被非法处置的链条；
2. 推断下游疑似销赃去向（黑加油点、工地、车队、社会小站等），评估经济损失和风险；
3. 提出从资金流、物流、票据流等方面打击上下游链条的建议。
"""
        else:
            role_desc = """
你是一名【综合案件分析专家】。
请综合空间位置、目标设施、作案手法、人员车辆、油品流向等多维度进行研判。
"""

        json_schema = """
请以JSON格式返回分析结果：
{
    "facts": ["已经确认的事实1", "已经确认的事实2"],
    "clues": ["可作为侦查抓手的线索1", "线索2"],
    "hypotheses": ["基于多案共性的推测1（需进一步核实）", "推测2"],
    "relations": ["案件之间的关联性分析1", "案件之间的关联性分析2"],
    "risk_assessment": {
        "level": "高风险/中风险/低风险",
        "factors": ["风险因素1", "风险因素2"]
    },
    "suggestions": ["针对该专家视角的建议1", "建议2"]
}
注意：facts 只能来自文本中已经出现的信息；clues 是可供侦查进一步核查的线索；hypotheses 必须以“可能/疑似”等方式表述，不得当作已经查明的事实。
"""

        return f"{role_desc}\n{base_intro}\n\n{json_schema}"

    async def analyze_cases(self, case_information: str) -> Dict:
        """分析案件（带专家角色化）"""
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
                    "features": [],
                    "relations": [],
                    "risk_assessment": {"level": "未知", "factors": []},
                    "suggestions": [],
                    "raw_content": content,
                }

            return result
        except Exception as e:
            return {
                "features": [],
                "relations": [],
                "risk_assessment": {"level": "错误", "factors": [str(e)]},
                "suggestions": [],
                "error": str(e),
            }
    
    async def evaluate_analysis(self, anonymous_analysis: Dict) -> Dict:
        """评价其他分析员的分析结果（仅评分）"""
        analysis_text = json.dumps(anonymous_analysis, ensure_ascii=False, indent=2)
        
        prompt = f"""
请评价以下匿名分析结果（满分10分）：

{analysis_text}

请提供以下内容（以JSON格式返回）：
{{
    "score": 8,
    "strengths": ["优点1", "优点2", "优点3"],
    "weaknesses": ["不足1", "不足2"],
    "suggestions": "改进建议"
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
        对多个匿名分析结果进行排名
        这是第二阶段的核心：每个LLM需要对所有其他LLM的回答进行排名
        """
        analyses_text = "\n\n".join([
            f"分析结果 {i+1}（匿名标识：{analysis.get('_anonymous_id', f'Response_{i+1}')}）：\n"
            f"{json.dumps(analysis, ensure_ascii=False, indent=2)}"
            for i, analysis in enumerate(anonymous_analyses)
        ])
        
        prompt = f"""
作为LLM委员会成员，请对以下匿名分析结果进行排名。

这些分析结果来自不同的LLM模型，但所有身份信息已被隐藏，你无法知道哪个结果来自哪个模型。
请仅基于分析的**准确性**和**洞察力**进行客观评价。

分析结果列表：
{analyses_text}

请提供以下内容（以JSON格式返回）：
{{
    "rankings": [
        {{
            "anonymous_id": "Response_1",
            "rank": 1,
            "score": 9,
            "reasoning": "为什么这个分析最好"
        }},
        {{
            "anonymous_id": "Response_2",
            "rank": 2,
            "score": 7,
            "reasoning": "为什么这个分析次之"
        }}
    ],
    "overall_comment": "整体评价和建议"
}}

注意：
- rankings 数组应按排名从高到低排序（rank=1 表示最好）
- 每个排名必须包含 anonymous_id（对应上面的匿名标识）
- score 是1-10的评分
- 必须对所有分析结果进行排名，不能遗漏
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

