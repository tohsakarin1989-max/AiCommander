# 地图MCP集成说明

## 概述

系统已集成地图服务运营商的MCP（Model Context Protocol）工具，结合AI分析，提供智能化的地图数据服务。

## 功能特性

### 1. 位置信息获取（逆地理编码）
- 根据经纬度获取详细地址信息
- 获取行政区划信息（省、市、区、街道）
- 用于案件位置标准化和地址补全

### 2. 周边POI搜索
- 搜索案件周边的关键设施（加油站、油库、管线等）
- 识别案件周边的潜在目标
- 用于案件关联分析和风险评估

### 3. 天气信息查询
- 获取案件发生时的天气信息
- 分析天气对案件的影响
- 用于案件模式分析

### 4. AI智能位置分析
- 结合MCP数据和AI模型
- 综合分析案件位置、周边环境、天气等因素
- 生成智能化的位置分析报告

## MCP工具配置

系统支持高德地图MCP工具，包括：

- `mcp_amap-amap-sse_maps_regeocode` - 逆地理编码
- `mcp_amap-amap-sse_maps_around_search` - 周边搜索
- `mcp_amap-amap-sse_maps_weather` - 天气查询
- `mcp_amap-amap-sse_maps_text_search` - 关键字搜索
- `mcp_amap-amap-sse_maps_geo` - 地理编码

## 使用方式

### 后端API

1. **获取位置信息**
   ```
   POST /api/map-mcp/location-info
   {
     "latitude": 39.908823,
     "longitude": 116.397470
   }
   ```

2. **搜索周边POI**
   ```
   POST /api/map-mcp/nearby-pois
   {
     "latitude": 39.908823,
     "longitude": 116.397470,
     "keywords": "加油站|油库|管线",
     "radius": 1000
   }
   ```

3. **获取天气信息**
   ```
   GET /api/map-mcp/weather/{city}
   ```

4. **AI智能分析案件位置**
   ```
   POST /api/map-mcp/analyze-case-location/{case_id}
   ```

### 前端使用

在地图页面：
1. 选择案件后，点击"位置信息"按钮查看详细地址
2. 点击"AI分析"按钮进行智能位置分析
3. 自动显示案件周边的关键设施

## 集成到圆桌会议

在圆桌会议中，系统会自动：
1. 获取案件位置信息
2. 搜索周边关键设施
3. 获取天气信息
4. 将这些信息提供给AI模型进行分析

## 配置说明

### MCP服务器配置

1. 确保MCP服务器已启动并配置高德地图MCP工具
2. 在系统设置中配置高德地图API密钥（如果需要）
3. MCP工具会自动通过MCP协议调用

### 注意事项

- MCP功能需要MCP服务器运行
- 如果MCP不可用，系统会返回基础信息
- AI分析功能需要配置AI模型

## 未来扩展

- 支持更多地图服务提供商（百度、腾讯等）
- 集成路径规划功能
- 集成距离测量功能
- 支持批量位置分析

