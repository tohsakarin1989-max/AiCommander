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
    """主持人智能体"""
    
    async def process(self, input_data: dict) -> dict:
        """实现抽象方法，处理输入并返回结果"""
        # ModeratorAgent 主要通过 format_case_information 和 generate_final_report 工作
        # 这里提供一个通用的 process 实现
        if "cases" in input_data:
            result = await self.format_case_information(
                input_data.get("cases", []),
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
    
    async def format_case_information(
        self, 
        cases: List[Dict], 
        geo_clues: Dict = None,
        map_mcp_data: Dict = None
    ) -> str:
        """
        格式化案件信息，包含地理线索分析
        geo_clues: 地理线索分析结果（热点、串案等）
        """
        if not cases:
            return "暂无案件信息"
        
        def _format_one(i: int, c: Dict) -> str:
            """格式化单条案件信息，包含经纬度和涉油特征"""
            lat = c.get("latitude")
            lng = c.get("longitude")
            geo_line = ""
            if lat is not None and lng is not None:
                geo_line = f"\n  经纬度：纬度 {lat}，经度 {lng}"
            oil_parts = []
            if c.get("oil_type"):
                oil_parts.append(f"油品类型：{c.get('oil_type')}")
            if c.get("oil_volume") is not None:
                oil_parts.append(f"数量：{c.get('oil_volume')} (约)")
            if c.get("facility_type"):
                oil_parts.append(f"目标设施：{c.get('facility_type')}")
            if c.get("modus_operandi"):
                oil_parts.append(f"作案手法：{c.get('modus_operandi')}")
            oil_line = ""
            if oil_parts:
                oil_line = "\n  涉油特征：" + "；".join(oil_parts)
            
            nearby_info = ""
            if c.get("nearby_case_count", 0) > 0:
                nearby_info = f"\n  附近案件：{c.get('nearby_case_count')} 起（1km内）"
            
            return (
                f"案件 {i+1}:\n"
                f"  编号：{c.get('case_number', 'N/A')}\n"
                f"  时间：{c.get('occurred_time', 'N/A')}\n"
                f"  地点：{c.get('location', 'N/A')}{geo_line}{nearby_info}\n"
                f"  类型：{c.get('case_type', 'N/A')}\n"
                f"  描述：{c.get('description', 'N/A')[:200]}{oil_line}"
            )

        case_list = "\n".join([_format_one(i, c) for i, c in enumerate(cases)])
        
        time_range = f"{cases[0].get('occurred_time', '')} 至 {cases[-1].get('occurred_time', '')}"
        
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
            map_mcp_text = "\n\n【地图MCP数据（位置、周边设施等）】\n"
            for case in cases:
                case_id = case.get("id") or None
                if case_id and case_id in map_mcp_data:
                    mcp_data = map_mcp_data[case_id]
                    map_mcp_text += f"\n案件 {case.get('case_number', '')}：\n"
                    if mcp_data.get("location_info", {}).get("success"):
                        loc = mcp_data["location_info"].get("location", {})
                        map_mcp_text += f"  详细地址：{loc.get('address', '未知')}\n"
                        map_mcp_text += f"  行政区划：{loc.get('province', '')} {loc.get('city', '')} {loc.get('district', '')}\n"
                    if mcp_data.get("nearby_pois", {}).get("success"):
                        pois = mcp_data["nearby_pois"].get("pois", [])
                        if pois:
                            map_mcp_text += f"  周边关键设施（{len(pois)} 个）：\n"
                            for poi in pois[:5]:  # 只显示前5个
                                map_mcp_text += f"    - {poi.get('name', '')}（{poi.get('type', '')}），距离 {poi.get('distance', 0)} 米\n"
        
        prompt = f"""
请将以下案件信息格式化为清晰的分析议题：

案件数量：{len(cases)}
时间范围：{time_range}

案件列表：
{case_list}
{geo_clues_text}
{map_mcp_text}

请特别注意：
- 仅依据案件文本和结构化特征中的已知信息进行分析，不得凭空捏造具体企业或个人；
- 对于尚未查明的经济链条、完整团伙结构等内容，只能给出"可能/疑似"的推测，并标记为需要进一步侦查验证；
- 建议性判断必须清楚区分"已知事实""可用线索""待核实推测"；
- **重点关注地理线索分析结果**（热点区域、串案等），结合地图信息进行空间研判；
- **充分利用地图MCP数据**（详细地址、周边关键设施等），分析地理位置在案件中的重要性。

请生成包含以下要点的分析议题：
1. 案件特征提取（时间、地点、经纬度、类型、模式等），区分明显事实与可能线索；
2. **案件空间关联性分析**（结合地理线索，分析相似案件、串并案可能性，是否属于同一街区/商圈/路段，是否存在热点区域）；
3. **地理位置研判**（根据地图信息分析案件分布规律，识别高风险区域，评估空间串案可能性）；
4. 风险评估（风险等级、风险因素，结合高发区域和周边环境）；
5. 巡逻建议（重点区域、时间段、资源配置，可参考经纬度分布、案件集中区域和地理线索分析结果），以"建议性措辞"给出，而非下定论。

请以清晰、结构化的格式输出分析议题。
"""
        
        try:
            response = await self.llm.ainvoke(prompt)
            return response.content
        except Exception as e:
            return f"格式化案件信息时出错: {str(e)}"
    
    async def generate_final_report(
        self,
        analyses: List[Dict],
        rankings: List[Dict] = None,
        aggregated_rankings: Dict = None
    ) -> Dict:
        """
        生成最终报告（基于LLM委员会三阶段流程）
        作为主席级LLM，汇总所有回答和排名，生成最终答案
        """
        # 格式化第一阶段的独立回答
        analyses_text = "\n\n".join([
            f"【分析结果 {i+1}】\n{json.dumps(analysis, ensure_ascii=False, indent=2)}"
            for i, analysis in enumerate(analyses)
        ])
        
        # 格式化第二阶段的排名结果
        rankings_text = ""
        if rankings:
            rankings_text = "\n\n【第二阶段：排名结果】\n"
            for i, ranking_result in enumerate(rankings):
                rankings_text += f"\n评价者 {i+1} 的排名：\n"
                rankings_text += json.dumps(ranking_result, ensure_ascii=False, indent=2)
                rankings_text += "\n"
        
        # 格式化综合排名
        aggregated_text = ""
        if aggregated_rankings and "rankings" in aggregated_rankings:
            aggregated_text = "\n\n【综合排名统计】\n"
            for index, rank_data in aggregated_rankings["rankings"].items():
                aggregated_text += f"分析结果 {int(index)+1}: "
                aggregated_text += f"平均得分 {rank_data['average_score']}, "
                aggregated_text += f"平均排名 {rank_data['average_rank']}, "
                aggregated_text += f"获得 {rank_data['vote_count']} 个评价\n"
        
        prompt = f"""
作为LLM委员会的主席，请汇总以下三个阶段的结果，生成最终综合分析报告：

【第一阶段：第一意见】
以下是所有LLM模型的独立分析结果（每个模型都基于相同的案件信息进行了独立分析）：

{analyses_text}
{rankings_text}
{aggregated_text}

请基于以下原则生成最终报告：
1. 综合所有LLM的独立分析，识别共识点和分歧点
2. 参考排名结果，优先采纳排名靠前的分析中的高质量洞察
3. 对于存在分歧的观点，应明确标注并说明不同模型的判断依据
4. 最终结论应基于事实和逻辑，而非简单多数投票

请生成包含以下内容的报告（以JSON格式返回）：
{{
    "summary": "执行摘要（综合所有LLM的分析）",
    "consensus_points": ["所有模型都认同的观点1", "共识点2"],
    "disagreement_points": ["存在分歧的观点1及不同模型的判断", "分歧点2"],
    "top_ranked_insights": ["来自排名靠前分析的关键洞察1", "关键洞察2"],
    "conclusions": "综合结论（基于事实和逻辑，参考排名结果）",
    "recommendations": ["建议1", "建议2"],
    "model_contributions": {{
        "analysis_1": "该分析的独特贡献",
        "analysis_2": "该分析的独特贡献"
    }},
    "ranking_summary": "排名结果的简要说明"
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
                result = json.loads(content)
                
                # 添加排名数据到结果中
                if aggregated_rankings:
                    result["aggregated_rankings"] = aggregated_rankings
                    
            except Exception as e:
                # 如果解析失败，返回原始内容
                result = {
                    "summary": content,
                    "consensus_points": [],
                    "disagreement_points": [],
                    "top_ranked_insights": [],
                    "conclusions": "",
                    "recommendations": [],
                    "model_contributions": {},
                    "ranking_summary": "排名解析失败",
                    "parse_error": str(e)
                }
            
            return result
        except Exception as e:
            return {
                "summary": f"生成报告时出错: {str(e)}",
                "consensus_points": [],
                "disagreement_points": [],
                "top_ranked_insights": [],
                "conclusions": "",
                "recommendations": [],
                "model_contributions": {},
                "ranking_summary": "生成失败",
                "error": str(e)
            }

