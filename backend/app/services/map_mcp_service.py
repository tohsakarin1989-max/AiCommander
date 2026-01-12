from typing import Dict, List, Optional
from app.utils.logger import logger
from app.utils.mcp_helper import MCPHelper

# 尝试导入MCP工具函数（如果可用）
# 在Cursor环境中，这些函数会自动可用
try:
    # 注意：MCP工具函数在Cursor环境中会自动可用
    # 这里提供一个接口层，实际调用会在有MCP工具的环境中自动完成
    MCP_AVAILABLE = True
except:
    MCP_AVAILABLE = False

class MapMCPService:
    """
    地图MCP服务
    通过MCP协议调用地图服务运营商的API，获取丰富的地理信息
    结合AI分析，提供智能化的地图数据服务
    """
    
    @staticmethod
    async def get_location_info(latitude: float, longitude: float) -> Dict:
        """
        获取位置信息（逆地理编码）
        返回：地址、行政区划、周边信息等
        通过MCP工具调用高德地图API
        
        注意：在Cursor环境中，MCP工具函数可以直接调用
        """
        try:
            location_str = f"{longitude},{latitude}"
            
            # 尝试通过MCP工具调用
            # 在Cursor环境中，MCP工具函数会自动可用
            # 这里提供一个接口，实际调用会在有MCP工具的环境中自动完成
            result = await MCPHelper.call_amap_regeocode(location_str)
            if result:
                # 解析MCP返回的结果
                if isinstance(result, dict):
                    return {
                        "success": True,
                        "location": {
                            "latitude": latitude,
                            "longitude": longitude,
                            "address": result.get("formatted_address") or result.get("address", ""),
                            "province": result.get("province", ""),
                            "city": result.get("city", ""),
                            "district": result.get("district", ""),
                            "street": result.get("street", ""),
                            "adcode": result.get("adcode", ""),
                        },
                        "raw_data": result,
                        "mcp_available": True
                    }
            
            # 如果MCP不可用，返回基础信息
            return {
                "success": True,
                "location": {
                    "latitude": latitude,
                    "longitude": longitude,
                    "coordinates": location_str,
                },
                "note": "MCP功能需要配置MCP服务器。当前返回基础坐标信息。请参考 MCP_INTEGRATION.md 配置高德地图MCP服务器。",
                "mcp_available": False
            }
        except Exception as e:
            logger.error(f"获取位置信息失败: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "location": {
                    "latitude": latitude,
                    "longitude": longitude,
                }
            }
    
    @staticmethod
    async def search_nearby_pois(
        latitude: float,
        longitude: float,
        keywords: str = "加油站|油库|管线|设施",
        radius: int = 1000
    ) -> Dict:
        """
        搜索周边POI（兴趣点）
        用于案件分析：识别案件周边的关键设施
        注意：此方法需要通过MCP客户端调用高德地图MCP工具
        """
        """
        搜索周边POI（兴趣点）
        用于案件分析：识别案件周边的关键设施
        注意：此方法需要通过MCP客户端调用高德地图MCP工具
        """
        try:
            location_str = f"{longitude},{latitude}"
            
            # 尝试通过MCP工具调用
            result = await MCPHelper.call_amap_around_search(
                keywords, location_str, str(radius)
            )
            if result:
                pois = []
                if result.get("pois"):
                    for poi in result.get("pois", []):
                        pois.append({
                            "name": poi.get("name", ""),
                            "type": poi.get("type", ""),
                            "address": poi.get("address", ""),
                            "location": poi.get("location", ""),
                            "distance": poi.get("distance", 0),
                            "tel": poi.get("tel", ""),
                        })
                
                return {
                    "success": True,
                    "pois": pois,
                    "count": len(pois),
                    "center": {
                        "latitude": latitude,
                        "longitude": longitude,
                    },
                    "radius": radius,
                    "keywords": keywords
                }
        except Exception as e:
            logger.error(f"搜索周边POI失败: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "pois": []
            }
    
    @staticmethod
    async def get_weather_info(city: str) -> Dict:
        """
        获取天气信息
        用于案件分析：分析天气对案件的影响
        注意：此方法需要通过MCP客户端调用高德地图MCP工具
        """
        try:
            # 尝试通过MCP工具调用
            result = await MCPHelper.call_amap_weather(city)
            if result:
                return {
                    "success": True,
                    "weather": result.get("lives", [{}])[0] if result.get("lives") else {},
                    "city": city
                }
            
            # 如果MCP不可用，返回基础信息
            return {
                "success": True,
                "weather": {},
                "city": city,
                "note": "MCP功能需要配置MCP服务器，当前返回空结果"
            }
        except Exception as e:
            logger.error(f"获取天气信息失败: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "city": city
            }
    
    @staticmethod
    async def search_with_adaptive_radius(
        latitude: float,
        longitude: float,
        keywords: str,
        min_radius: int = 10000,
        max_radius: int = 50000,
        target_count: int = 10,
        step: int = 5000
    ) -> Dict:
        """
        自适应半径搜索
        根据实际找到的POI数量动态调整搜索范围
        适用于偏远地区，人烟稀少的情况
        """
        current_radius = min_radius
        best_result = None
        
        while current_radius <= max_radius:
            result = await MapMCPService.search_nearby_pois(
                latitude,
                longitude,
                keywords=keywords,
                radius=current_radius
            )
            
            if result.get("success") and result.get("pois"):
                count = len(result.get("pois", []))
                result["actual_radius"] = current_radius
                
                # 如果找到足够的结果，或者已经达到最大半径，返回结果
                if count >= target_count or current_radius >= max_radius:
                    return result
                
                # 保存当前最佳结果
                if best_result is None or count > len(best_result.get("pois", [])):
                    best_result = result
            
            # 扩大搜索范围
            current_radius += step
        
        # 返回最佳结果（即使没有达到目标数量）
        if best_result:
            return best_result
        
        # 如果没有找到任何结果，返回空结果
        return {
            "success": True,
            "pois": [],
            "count": 0,
            "actual_radius": max_radius,
            "center": {
                "latitude": latitude,
                "longitude": longitude,
            },
            "radius": max_radius,
            "keywords": keywords
        }
    
    @staticmethod
    async def get_comprehensive_location_analysis(
        latitude: float,
        longitude: float,
        min_village_radius: int = 20000,  # 默认20公里起
        max_village_radius: int = 100000,  # 最大100公里
        min_gas_radius: int = 20000,  # 加油站20公里起
        max_gas_radius: int = 100000,  # 最大100公里
        min_refinery_radius: int = 30000,  # 炼化点30公里起
        max_refinery_radius: int = 150000,  # 最大150公里
    ) -> Dict:
        """
        获取全面的位置分析数据
        包括：位置信息、周边村屯、加油站、炼化点、路口等
        
        针对偏远地区优化：
        - 使用自适应半径搜索，根据实际找到的村屯数量动态调整范围
        - 偏远地区人烟稀少，需要更大的搜索范围
        """
        try:
            location_str = f"{longitude},{latitude}"
            
            # 1. 获取位置信息
            location_info = await MapMCPService.get_location_info(latitude, longitude)
            
            # 2. 搜索周边村屯、社区（自适应半径，目标至少10个）
            # 偏远地区可能村屯稀少，需要扩大范围
            villages = await MapMCPService.search_with_adaptive_radius(
                latitude,
                longitude,
                keywords="村庄|村|社区|居民区|小区|屯|镇|乡",
                min_radius=min_village_radius,
                max_radius=max_village_radius,
                target_count=10,  # 目标找到至少10个村屯
                step=10000  # 每次扩大10公里
            )
            
            # 3. 搜索加油站（自适应半径，目标至少5个）
            gas_stations = await MapMCPService.search_with_adaptive_radius(
                latitude,
                longitude,
                keywords="加油站|加气站",
                min_radius=min_gas_radius,
                max_radius=max_gas_radius,
                target_count=5,  # 目标找到至少5个加油站
                step=10000
            )
            
            # 4. 搜索炼化点、化工厂（自适应半径，目标至少3个）
            refineries = await MapMCPService.search_with_adaptive_radius(
                latitude,
                longitude,
                keywords="炼化|炼油|化工厂|石化|油库|储油|炼油厂",
                min_radius=min_refinery_radius,
                max_radius=max_refinery_radius,
                target_count=3,  # 目标找到至少3个炼化点
                step=15000  # 每次扩大15公里
            )
            
            # 5. 搜索路口、道路（固定范围，因为路口相对较多）
            intersections = await MapMCPService.search_nearby_pois(
                latitude,
                longitude,
                keywords="路口|交叉口|道路|公路|国道|省道|高速|高速公路",
                radius=20000  # 路口搜索20公里
            )
            
            # 计算实际使用的搜索范围统计
            search_stats = {
                "villages_radius": villages.get("actual_radius", min_village_radius),
                "gas_stations_radius": gas_stations.get("actual_radius", min_gas_radius),
                "refineries_radius": refineries.get("actual_radius", min_refinery_radius),
                "intersections_radius": intersections.get("radius", 20000),
                "is_remote_area": villages.get("count", 0) < 5  # 如果村屯少于5个，认为是偏远地区
            }
            
            return {
                "success": True,
                "location_info": location_info,
                "villages": villages,
                "gas_stations": gas_stations,
                "refineries": refineries,
                "intersections": intersections,
                "search_stats": search_stats,
                "center": {
                    "latitude": latitude,
                    "longitude": longitude
                }
            }
        except Exception as e:
            logger.error(f"获取全面位置分析失败: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    @staticmethod
    async def analyze_approach_routes(
        latitude: float,
        longitude: float,
        case_description: str = "",
        is_remote: bool = False
    ) -> Dict:
        """
        分析可能的来路（路径分析）
        基于周边路口和道路，分析案发地点可能的来路方向
        
        针对偏远地区，扩大搜索范围
        """
        try:
            location_str = f"{longitude},{latitude}"
            
            # 根据是否偏远地区调整搜索范围
            route_radius = 50000 if is_remote else 20000  # 偏远地区50公里，一般地区20公里
            
            # 1. 搜索周边路口和道路（自适应半径）
            intersections = await MapMCPService.search_with_adaptive_radius(
                latitude,
                longitude,
                keywords="路口|交叉口|道路|公路|国道|省道|高速|高速公路|县道|乡道",
                min_radius=20000,
                max_radius=route_radius,
                target_count=10,  # 目标找到至少10个路口/道路
                step=10000
            )
            
            # 2. 分析可能的来路方向
            approach_analysis = {
                "nearby_intersections": intersections.get("pois", []) if intersections.get("success") else [],
                "possible_approaches": [],
                "analysis": "",
                "search_radius": intersections.get("actual_radius", route_radius)
            }
            
            if intersections.get("pois"):
                # 分析主要路口和道路
                # 偏远地区扩大范围，不限制距离
                main_roads = []
                max_distance = 50000 if is_remote else 10000  # 偏远地区50公里，一般地区10公里
                
                for poi in intersections["pois"]:
                    distance = poi.get("distance", 0)
                    if distance <= max_distance:
                        main_roads.append({
                            "name": poi.get("name", ""),
                            "type": poi.get("type", ""),
                            "distance": distance,
                            "address": poi.get("address", ""),
                            "direction": "需要根据位置关系判断"
                        })
                
                # 按距离排序，取前15个
                main_roads.sort(key=lambda x: x.get("distance", 0))
                approach_analysis["possible_approaches"] = main_roads[:15]
                approach_analysis["analysis"] = f"在 {intersections.get('actual_radius', route_radius)/1000:.1f} 公里范围内发现 {len(main_roads)} 个主要路口/道路，可能从这些方向接近案发地点"
            
            return {
                "success": True,
                "approach_analysis": approach_analysis,
                "center": {
                    "latitude": latitude,
                    "longitude": longitude
                }
            }
        except Exception as e:
            logger.error(f"分析来路失败: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    @staticmethod
    async def analyze_case_location_with_ai(
        latitude: float,
        longitude: float,
        case_description: str,
        llm
    ) -> Dict:
        """
        结合AI和地图MCP数据，智能分析案件位置
        包括：位置信息、周边村屯、加油站、炼化点、来路分析等
        """
        try:
            # 1. 获取全面的位置分析数据
            comprehensive_data = await MapMCPService.get_comprehensive_location_analysis(
                latitude, longitude
            )
            
            # 判断是否为偏远地区
            is_remote = comprehensive_data.get("search_stats", {}).get("is_remote_area", False)
            
            # 2. 分析可能的来路（传入偏远地区标识）
            approach_analysis = await MapMCPService.analyze_approach_routes(
                latitude, longitude, case_description, is_remote
            )
            
            # 3. 获取天气信息
            city = comprehensive_data.get("location_info", {}).get("location", {}).get("city", "")
            weather_info = {}
            if city:
                weather_info = await MapMCPService.get_weather_info(city)
            
            # 4. 构建AI分析提示
            location_info = comprehensive_data.get("location_info", {})
            villages = comprehensive_data.get("villages", {})
            gas_stations = comprehensive_data.get("gas_stations", {})
            refineries = comprehensive_data.get("refineries", {})
            intersections = comprehensive_data.get("intersections", {})
            
            prompt = f"""
基于以下案件信息和地图MCP数据，进行智能分析：

【案件描述】
{case_description}

【位置信息】
- 坐标：纬度 {latitude}, 经度 {longitude}
- 详细地址：{location_info.get('location', {}).get('address', '未知')}
- 行政区划：{location_info.get('location', {}).get('province', '')} {location_info.get('location', {}).get('city', '')} {location_info.get('location', {}).get('district', '')}
- 街道：{location_info.get('location', {}).get('street', '未知')}

【周边村屯/社区】
"""
            
            if villages.get("pois"):
                prompt += f"共发现 {villages['count']} 个村屯/社区：\n"
                for poi in villages["pois"][:10]:
                    prompt += f"- {poi['name']}（{poi['type']}），距离 {poi['distance']} 米，地址：{poi['address']}\n"
            else:
                prompt += "未发现明显的村屯/社区\n"
            
            prompt += "\n【周边加油站】\n"
            if gas_stations.get("pois"):
                prompt += f"共发现 {gas_stations['count']} 个加油站/加气站：\n"
                for poi in gas_stations["pois"][:10]:
                    prompt += f"- {poi['name']}（{poi['type']}），距离 {poi['distance']} 米，地址：{poi['address']}"
                    if poi.get('tel'):
                        prompt += f"，电话：{poi['tel']}"
                    prompt += "\n"
            else:
                prompt += "未发现加油站\n"
            
            prompt += "\n【周边炼化点/储油设施】\n"
            if refineries.get("pois"):
                prompt += f"共发现 {refineries['count']} 个炼化点/储油设施：\n"
                for poi in refineries["pois"][:10]:
                    prompt += f"- {poi['name']}（{poi['type']}），距离 {poi['distance']} 米，地址：{poi['address']}\n"
            else:
                prompt += "未发现炼化点/储油设施\n"
            
            prompt += "\n【周边路口/道路】\n"
            if intersections.get("pois"):
                prompt += f"共发现 {intersections['count']} 个路口/道路：\n"
                for poi in intersections["pois"][:10]:
                    prompt += f"- {poi['name']}（{poi['type']}），距离 {poi['distance']} 米，地址：{poi['address']}\n"
            else:
                prompt += "未发现明显的路口/道路\n"
            
            # 来路分析
            if approach_analysis.get("approach_analysis", {}).get("possible_approaches"):
                prompt += "\n【可能的来路分析】\n"
                for route in approach_analysis["approach_analysis"]["possible_approaches"][:5]:
                    prompt += f"- 可能从 {route['name']}（{route['distance']} 米）方向接近\n"
            
            if weather_info.get("weather"):
                weather = weather_info["weather"]
                prompt += f"\n【天气信息】\n- 天气：{weather.get('weather', '未知')}\n- 温度：{weather.get('temperature', '未知')}°C\n- 风向：{weather.get('winddirection', '未知')}\n- 风力：{weather.get('windpower', '未知')}\n"
            
            # 添加搜索范围信息
            search_stats = comprehensive_data.get("search_stats", {})
            prompt += f"""
【搜索范围说明】
- 村屯搜索范围：{search_stats.get('villages_radius', 0)/1000:.1f} 公里（共找到 {villages.get('count', 0)} 个）
- 加油站搜索范围：{search_stats.get('gas_stations_radius', 0)/1000:.1f} 公里（共找到 {gas_stations.get('count', 0)} 个）
- 炼化点搜索范围：{search_stats.get('refineries_radius', 0)/1000:.1f} 公里（共找到 {refineries.get('count', 0)} 个）
- 路口搜索范围：{approach_analysis.get('search_radius', 0)/1000:.1f} 公里
- 是否偏远地区：{'是（人烟稀少，已扩大搜索范围）' if is_remote else '否'}
"""
            
            prompt += """
请基于以上信息，进行综合分析：
1. **地理位置特征**：该位置的地理特征、周边环境、交通情况，特别注意是否为偏远地区
2. **周边村屯分析**：周边村屯分布情况，可能的人员来源。如果村屯稀少，说明该地区人烟稀少的特点
3. **加油站/炼化点分析**：周边加油站和炼化点的分布，可能的关联性。注意搜索范围较大，说明该地区设施稀少
4. **来路分析**：基于周边路口和道路，分析可能的来路方向，嫌疑人可能从哪些路口接近案发地点。特别注意偏远地区可能只有少数几条主要道路
5. **风险评估**：基于地图数据的综合风险评估，特别考虑偏远地区的特点（人烟稀少、监控少、交通不便等）
6. **防控建议**：针对该位置的具体防控措施建议，考虑偏远地区的实际情况

请以JSON格式返回分析结果，包含以下字段：
{
    "geographic_features": "地理位置特征描述（包括是否偏远地区）",
    "villages_analysis": "周边村屯分析（说明搜索范围和找到的数量）",
    "gas_stations_analysis": "加油站分析（说明搜索范围和找到的数量）",
    "refineries_analysis": "炼化点分析（说明搜索范围和找到的数量）",
    "approach_routes": ["可能的来路1", "可能的来路2"],
    "risk_assessment": "风险评估（特别考虑偏远地区特点）",
    "prevention_suggestions": ["防控建议1", "防控建议2"]
}
"""
            
            # 5. 调用AI进行分析
            response = await llm.ainvoke(prompt)
            content = response.content
            
            # 解析AI返回的JSON
            import json
            try:
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                ai_analysis = json.loads(content)
            except:
                ai_analysis = {
                    "analysis": content,
                    "parse_error": True
                }
            
            return {
                "success": True,
                "location_info": location_info,
                "comprehensive_data": comprehensive_data,
                "approach_analysis": approach_analysis,
                "weather_info": weather_info,
                "ai_analysis": ai_analysis
            }
            
        except Exception as e:
            logger.error(f"AI分析案件位置失败: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    @staticmethod
    async def enrich_case_with_map_data(case: 'Case', llm) -> Dict:
        """
        为案件丰富地图数据
        结合MCP和AI，为案件添加丰富的地理信息
        """
        if not case.latitude or not case.longitude:
            return {
                "success": False,
                "message": "案件缺少经纬度信息"
            }
        
        return await MapMCPService.analyze_case_location_with_ai(
            case.latitude,
            case.longitude,
            case.description or "",
            llm
        )

