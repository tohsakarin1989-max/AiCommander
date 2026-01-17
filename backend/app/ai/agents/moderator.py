from app.ai.agents.base_agent import BaseAgent
from typing import List, Dict
import json

try:
    # 兼容新版本 langchain-core
    from langchain_core.prompts import ChatPromptTemplate  # type: ignore
except Exception:  # pragma: no cover
    # 兼容旧版本 langchain
    from langchain.prompts import ChatPromptTemplate  # type: ignore


class ModeratorAgent(BaseAgent):
    """
    主持人智能体（区域研判导向）

    核心职责：
    1. 整理事件信息，构建区域研判议题
    2. 汇总各专家分析，提炼共识和最佳实践
    3. 生成综合研判报告（经验总结 + 巡逻建议）
    """

    async def process(self, input_data: dict) -> dict:
        """实现抽象方法，处理输入并返回结果"""
        if "cases" in input_data or "events" in input_data:
            # 支持 cases 和 events 两种输入格式
            data = input_data.get("events") or input_data.get("cases", [])
            result = await self.format_event_information(
                data,
                input_data.get("area_context"),
                input_data.get("geo_clues"),
                input_data.get("map_mcp_data")
            )
            return {"formatted_info": result}
        elif "analyses" in input_data:
            result = await self.generate_final_report(
                input_data.get("analyses", []),
                input_data.get("rankings"),
                input_data.get("aggregated_rankings")
            )
            return result
        else:
            return {"error": "Unknown input format"}
    
    async def format_event_information(
        self,
        events: List[Dict],
        area_context: Dict = None,
        geo_clues: Dict = None,
        map_mcp_data: Dict = None
    ) -> str:
        """
        格式化事件信息，构建区域研判议题

        核心目标：从已破获案件/事件中提炼经验，识别区域风险，指导巡逻防控

        Args:
            events: 事件/案件列表
            area_context: 区域背景信息（如区域统计、历史事件等）
            geo_clues: 地理线索分析结果
            map_mcp_data: 地图MCP数据
        """
        if not events:
            return "暂无事件信息"

        def _format_one(i: int, e: Dict) -> str:
            """格式化单条事件信息"""
            lat = e.get("latitude")
            lng = e.get("longitude")
            geo_line = ""
            if lat is not None and lng is not None:
                geo_line = f"\n  经纬度：纬度 {lat}，经度 {lng}"

            # 关联村屯信息
            village_line = ""
            if e.get("village_name"):
                village_line = f"\n  关联村屯：{e.get('village_name')}"
                if e.get("village_distance_km"):
                    village_line += f"（距离 {e.get('village_distance_km')} 公里）"

            # 涉油特征
            oil_parts = []
            if e.get("oil_type"):
                oil_parts.append(f"油品类型：{e.get('oil_type')}")
            if e.get("oil_volume_liters") or e.get("oil_volume"):
                vol = e.get("oil_volume_liters") or e.get("oil_volume")
                oil_parts.append(f"数量：约 {vol} 升")
            if e.get("facility_type"):
                oil_parts.append(f"目标设施：{e.get('facility_type')}")
            if e.get("modus_operandi"):
                oil_parts.append(f"作案手法：{e.get('modus_operandi')}")
            oil_line = ""
            if oil_parts:
                oil_line = "\n  涉油特征：" + "；".join(oil_parts)

            # 涉及车辆
            vehicle_line = ""
            vehicles = e.get("vehicles", [])
            if vehicles:
                if isinstance(vehicles, list):
                    v_info = [f"{v.get('plate', '未知')}({v.get('type', '')})" for v in vehicles]
                    vehicle_line = f"\n  涉及车辆：{', '.join(v_info)}"
                elif isinstance(vehicles, str):
                    vehicle_line = f"\n  涉及车辆：{vehicles}"

            # 事件类型（兼容 event_type 和 case_type）
            event_type = e.get("event_type") or e.get("case_type", "N/A")
            event_number = e.get("event_number") or e.get("case_number", "N/A")

            return (
                f"事件 {i+1}:\n"
                f"  编号：{event_number}\n"
                f"  类型：{event_type}\n"
                f"  时间：{e.get('occurred_time', 'N/A')}\n"
                f"  地点：{e.get('location', 'N/A')}{geo_line}{village_line}\n"
                f"  描述：{(e.get('description') or e.get('title', 'N/A'))[:200]}{oil_line}{vehicle_line}"
            )

        event_list = "\n".join([_format_one(i, e) for i, e in enumerate(events)])

        # 时间范围
        times = [e.get('occurred_time', '') for e in events if e.get('occurred_time')]
        time_range = f"{times[0]} 至 {times[-1]}" if times else "未知"

        # 区域背景信息
        area_context_text = ""
        if area_context:
            area_context_text = "\n\n【区域背景】\n"
            if area_context.get("area_name"):
                area_context_text += f"研判区域：{area_context.get('area_name')}\n"
            if area_context.get("total_events"):
                area_context_text += f"历史事件总数：{area_context.get('total_events')} 起\n"
            if area_context.get("risk_level"):
                area_context_text += f"当前风险等级：{area_context.get('risk_level')}\n"
            if area_context.get("event_types_count"):
                counts = area_context.get("event_types_count", {})
                area_context_text += f"事件类型分布：{json.dumps(counts, ensure_ascii=False)}\n"

        # 格式化地理线索信息
        geo_clues_text = ""
        if geo_clues and geo_clues.get("clues"):
            geo_clues_text = "\n\n【地理线索分析】\n"
            for clue in geo_clues.get("clues", []):
                geo_clues_text += f"\n{clue.get('title', '')}：{clue.get('description', '')}\n"
                if clue.get('suggestions'):
                    geo_clues_text += f"建议：{'; '.join(clue.get('suggestions', []))}\n"

        # 格式化地图MCP数据
        map_mcp_text = ""
        if map_mcp_data:
            map_mcp_text = "\n\n【地图位置信息】\n"
            for event in events:
                event_id = event.get("id") or None
                if event_id and event_id in map_mcp_data:
                    mcp_data = map_mcp_data[event_id]
                    event_number = event.get("event_number") or event.get("case_number", "")
                    map_mcp_text += f"\n事件 {event_number}：\n"
                    if mcp_data.get("location_info", {}).get("success"):
                        loc = mcp_data["location_info"].get("location", {})
                        map_mcp_text += f"  详细地址：{loc.get('address', '未知')}\n"
                        map_mcp_text += f"  行政区划：{loc.get('province', '')} {loc.get('city', '')} {loc.get('district', '')}\n"
                    if mcp_data.get("nearby_pois", {}).get("success"):
                        pois = mcp_data["nearby_pois"].get("pois", [])
                        if pois:
                            map_mcp_text += f"  周边设施：{', '.join([p.get('name', '') for p in pois[:3]])}\n"

        prompt = f"""
【研判任务说明】
以下是已经破获的涉油案件/事件信息。请整理这些信息，为专家组研判会议构建分析议题。

【重要】研判目标是：
1. 从已破获案件中提炼经验和规律
2. 识别区域风险，评估哪些区域需要重点关注
3. 为未来巡逻防控提供具体可行的建议

请勿：
- 试图追查嫌疑人或提供侦查方向
- 给出需要进一步侦查核实的推测

事件数量：{len(events)}
时间范围：{time_range}

【事件列表】
{event_list}
{area_context_text}
{geo_clues_text}
{map_mcp_text}

请生成结构化的研判议题，包含以下要点：

1. 【事件概况】
   - 事件时空分布特征
   - 主要涉及的村屯/区域
   - 事件类型分布

2. 【规律识别】
   - 时间规律：是否存在发案高峰时段/月份？
   - 空间规律：事件是否在某些区域聚集？
   - 手法规律：是否存在相似的作案手法？

3. 【关联分析】
   - 哪些事件可能存在关联？（如同一区域的囤油点和查获车辆）
   - 关联的依据是什么？

4. 【区域风险评估】
   - 哪些村屯/区域风险较高？
   - 风险因素有哪些？

5. 【巡逻建议要点】
   - 应重点关注哪些区域？
   - 应在哪些时段加强巡逻？
   - 巡逻时应关注什么？

请以清晰、结构化的格式输出，便于专家组讨论。
"""

        try:
            response = await self.llm.ainvoke(prompt)
            return response.content
        except Exception as e:
            return f"格式化事件信息时出错: {str(e)}"

    # 保留旧方法以保持向后兼容
    async def format_case_information(
        self,
        cases: List[Dict],
        geo_clues: Dict = None,
        map_mcp_data: Dict = None
    ) -> str:
        """向后兼容：格式化案件信息"""
        return await self.format_event_information(cases, None, geo_clues, map_mcp_data)
    
    async def generate_final_report(
        self,
        analyses: List[Dict],
        rankings: List[Dict] = None,
        aggregated_rankings: Dict = None
    ) -> Dict:
        """
        生成综合研判报告（经验提炼 + 巡逻建议导向）

        核心目标：
        1. 汇总各专家的规律识别和关联分析
        2. 整合巡逻建议，形成可执行的行动方案
        3. 提炼核心经验，形成知识沉淀
        """
        # 格式化第一阶段的独立研判
        analyses_text = "\n\n".join([
            f"【研判结果 {i+1}】\n{json.dumps(analysis, ensure_ascii=False, indent=2)}"
            for i, analysis in enumerate(analyses)
        ])

        # 格式化第二阶段的排名结果
        rankings_text = ""
        if rankings:
            rankings_text = "\n\n【第二阶段：研判质量评估】\n"
            for i, ranking_result in enumerate(rankings):
                rankings_text += f"\n评价者 {i+1} 的排名：\n"
                rankings_text += json.dumps(ranking_result, ensure_ascii=False, indent=2)
                rankings_text += "\n"

        # 格式化综合排名
        aggregated_text = ""
        if aggregated_rankings and "rankings" in aggregated_rankings:
            aggregated_text = "\n\n【综合排名统计】\n"
            for index, rank_data in aggregated_rankings["rankings"].items():
                aggregated_text += f"研判结果 {int(index)+1}: "
                aggregated_text += f"平均得分 {rank_data['average_score']}, "
                aggregated_text += f"平均排名 {rank_data['average_rank']}, "
                aggregated_text += f"获得 {rank_data['vote_count']} 个评价\n"

        prompt = f"""
作为研判委员会主席，请汇总各专家的研判结果，生成综合研判报告。

【重要】本报告的目标是：
1. 提炼各专家识别的规律和关联
2. 整合形成可执行的巡逻建议
3. 总结核心经验，指导未来防控工作

请勿：
- 给出追查嫌疑人的建议
- 提供需要进一步侦查的方向

【第一阶段：各专家独立研判】
{analyses_text}
{rankings_text}
{aggregated_text}

请生成综合研判报告（以JSON格式返回）：
{{
    "summary": "研判摘要（2-3句话概括主要发现和建议）",

    "patterns_consensus": [
        {{
            "type": "规律类型",
            "description": "规律描述",
            "confidence": "high/medium/low",
            "supporting_experts": 3
        }}
    ],

    "area_risk_assessment": [
        {{
            "area_name": "村屯/区域名称",
            "risk_level": "high/medium/low",
            "risk_factors": ["因素1", "因素2"],
            "priority_rank": 1
        }}
    ],

    "key_correlations": [
        {{
            "description": "关联描述",
            "implication": "这意味着什么",
            "action_required": "建议行动"
        }}
    ],

    "patrol_action_plan": [
        {{
            "priority": 1,
            "location": "具体地点/路段",
            "timing": "建议时间",
            "focus": ["关注重点1", "关注重点2"],
            "method": "巡逻方式（车巡/步巡/蹲守）"
        }}
    ],

    "search_priorities": [
        {{
            "target": "排查目标",
            "area": "排查区域",
            "rationale": "为什么要排查这里"
        }}
    ],

    "experience_extraction": [
        "从这些案件中提炼的核心经验1",
        "核心经验2"
    ],

    "expert_contributions": {{
        "research_1": "该研判的独特贡献",
        "research_2": "该研判的独特贡献"
    }},

    "next_steps": [
        "后续工作建议1",
        "后续工作建议2"
    ]
}}

注意：
- 优先采纳排名靠前的研判中的高质量洞察
- patrol_action_plan 应具体、可执行，按优先级排序
- experience_extraction 是知识沉淀，应简洁有力
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
                result = json.loads(content)

                # 添加排名数据到结果中
                if aggregated_rankings:
                    result["aggregated_rankings"] = aggregated_rankings

            except Exception as e:
                # 如果解析失败，返回原始内容
                result = {
                    "summary": content,
                    "patterns_consensus": [],
                    "area_risk_assessment": [],
                    "key_correlations": [],
                    "patrol_action_plan": [],
                    "search_priorities": [],
                    "experience_extraction": [],
                    "expert_contributions": {},
                    "next_steps": [],
                    "parse_error": str(e)
                }

            return result
        except Exception as e:
            return {
                "summary": f"生成报告时出错: {str(e)}",
                "patterns_consensus": [],
                "area_risk_assessment": [],
                "key_correlations": [],
                "patrol_action_plan": [],
                "search_priorities": [],
                "experience_extraction": [],
                "expert_contributions": {},
                "next_steps": [],
                "error": str(e)
            }

