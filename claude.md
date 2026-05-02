# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

AiCommander 是一个 AI 驱动的案件分析系统，专注于涉油案件分析，核心特性是"圆桌会议"模式——多个 AI 智能体协作研判案件。

## 常用命令

### 启动服务

```bash
# Docker 全栈启动（推荐）
./start.sh
# 停止
./stop.sh

# 本地后端开发（使用内置 SQLite，无需外部数据库）
cd backend && source venv/bin/activate
pip install -r requirements.txt  # 首次
python init_db.py                # 首次
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 本地前端开发
cd frontend && npm install && npm run dev
```

### 测试

```bash
# 后端测试（使用内存 SQLite，无需外部依赖）
cd backend && source venv/bin/activate

pytest                                              # 全部测试
pytest -v                                           # 详细输出

# 运行单个测试文件（在 backend/ 目录下执行）
pytest tests/test_case_service.py
pytest tests/test_geo_analysis.py
pytest tests/test_meeting_manager.py
pytest tests/test_analyst_prompts.py
pytest tests/test_moderator_prompts.py

# 运行单个测试函数
pytest tests/test_case_service.py::test_case_number_generation_increments
```

### 数据库迁移

```bash
cd backend
alembic upgrade head                        # 应用迁移
alembic revision --autogenerate -m "描述"   # 生成迁移
```

### 前端构建

```bash
cd frontend
npm run build    # 生产构建
npm run preview  # 预览构建结果
```

## 核心架构

### 圆桌会议系统（AI 多智能体协作）

会议流程分三阶段，由 `MeetingManager` 协调：

1. **第一阶段 - 独立分析**：所有 `AnalystAgent` 并行独立分析案件
2. **第二阶段 - 匿名互评**：每个分析员匿名审查并排名其他分析员的结果（通过 `Anonymizer` 去标识）
3. **第三阶段 - 综合报告**：`ModeratorAgent` 汇总所有分析和排名，生成最终报告

关键文件：
- `backend/app/ai/meeting_manager.py` - 会议协调器，管理三阶段流程
- `backend/app/ai/agents/base_agent.py` - 智能体抽象基类
- `backend/app/ai/agents/analyst.py` - 分析师智能体（支持 `config.specialty` 专业化）
- `backend/app/ai/agents/moderator.py` - 主持人智能体
- `backend/app/ai/model_factory.py` - LLM 工厂（支持 OpenAI/Anthropic/兼容接口）
- `backend/app/ai/anonymizer.py` - 匿名化处理器

### 后端分层架构

```
backend/app/
├── api/           # FastAPI 路由（REST 端点）
├── services/      # 业务逻辑层
├── repositories/  # 数据访问层
├── models/        # SQLAlchemy 实体
├── ai/            # AI/LLM 核心（智能体、模型工厂）
└── tasks/         # Celery 异步任务
```

路由注册在 `backend/app/main.py`，主要 API 模块：
- `/api/cases` - 案件管理
- `/api/meetings` - 圆桌会议
- `/api/models` - AI 模型配置
- `/api/reports` - 分析报告
- `/api/assistant` - AI 助手
- `/api/map-mcp` - 高德地图 MCP 集成

### 前端结构

```
frontend/src/
├── pages/         # 页面视图（Cases, Meetings, Reports 等）
├── components/    # 复用组件
└── services/      # API 调用封装
```

技术栈：React 18 + TypeScript + Ant Design + Zustand（状态）+ React Query（数据请求）+ ECharts（图表）

## 环境变量

必需：
- `SECRET_KEY` - JWT 认证密钥

可选（有默认值）：
- `DATABASE_URL` - 默认 `sqlite:///./aicommander.db`
- `REDIS_URL` - 默认 `redis://localhost:6379/0`
- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` - AI 模型密钥
- `FRONTEND_URL` - 前端地址，用于 CORS

## 开发原则

### 优化原则
- **简洁性**：代码简洁易用，避免过度设计
- **可读性**：逻辑清晰，适当注释
- **命名规范**：模块、接口命名统一、语义明确
- **复用性**：提取公共逻辑为工具函数，遵循 DRY 原则

### 迭代原则
- **功能升级**：基于现有功能的高级版本
- **功能融合**：多项功能智能整合（如一键研判）
- **用户便利**：提供实实在在的便利性
- **智能化**：引入 AI 能力提升效率

## 编码规范

### 后端
- Python PEP 8，4 空格缩进
- 路由模块：`app/api/<domain>.py`
- 服务层：`app/services/<domain>_service.py`
- 工具函数：`app/utils/<module>.py`
- 环境变量全大写下划线命名

### 前端
- TypeScript 严格模式
- 组件文件 PascalCase（如 `CaseList.tsx`）
- **类型定义集中在 `frontend/src/types/index.ts`**
- **API 服务使用命名空间风格**（如 `eventApi.list()`）

### 测试
- 使用 pytest，测试文件放 `backend/tests/test_*.py`
- 优先使用内存 SQLite 隔离测试数据
- 新增 API 应至少覆盖成功和失败路径

## 业务领域

涉油案件专用字段：油品类型、涉案数量/价值、设施类型（管线/油库/加油站/油罐车）、安全等级、作案手法、嫌疑人角色

## 前端服务层结构

### 统一 API 服务风格

所有 API 服务使用命名空间导出，便于代码提示和维护：

```typescript
// frontend/src/services/index.ts
export { casesApi } from './cases'      // 案件管理
export { eventApi } from './events'      // 事件管理
export { patrolApi } from './patrols'    // 巡逻记录
export { gangApi } from './gangs'        // 团伙分析
export { analysisApi } from './analysis' // 分析报告（智能研判、部署建议、图谱）
export { aiApi } from './ai'             // AI 服务（会议、助手、结论、智能体）
export { configApi } from './config'     // 系统配置（模型、系统参数）
```

### 类型定义

所有共享类型集中定义在 `frontend/src/types/index.ts`，包括：
- 案件相关：`Case`, `CaseStatistics`, `CaseCreateData`
- 会议相关：`Meeting`, `MeetingTemplate`, `MeetingReport`
- AI 相关：`AIModel`, `Conversation`, `ChatMessage`, `AgentConfig`
- 分析相关：`SmartAnalysisReport`, `TrajectoryAnalysis`, `GangProfile`
- 配置相关：`SystemConfig`, `Event`, `PatrolRecord`

## 后端工具模块

### 地理计算工具 (`app/utils/geo.py`)

提供经纬度相关的通用计算函数：

| 函数 | 用途 |
|------|------|
| `haversine_km()` | 计算两点球面距离（公里） |
| `bounding_box()` | 计算经纬度边界框 |
| `calculate_bearing()` | 计算方向角（0-360度） |
| `calculate_center()` | 计算多点几何中心 |
| `destination_point()` | 从起点沿方向移动到目标点 |
| `create_grid_key()` | 生成网格索引键 |
| `km_to_deg()` | 公里转度数 |

### 分析服务

| 服务 | 职责 |
|------|------|
| `GeoAnalysisService` | 静态空间分析（热点识别、串案分析、地理分布） |
| `TrajectoryService` | 时序轨迹分析（轨迹提取、模式分析、位置预测） |
| `SmartAnalysisService` | 一键智能研判（融合热点、团伙、模式、部署建议） |
| `GangAnalysisService` | 团伙识别与分析 |

## 智能研判系统

### 一键智能研判 (`/api/deployment/smart-analysis`)

融合多个分析模块，生成综合研判报告：

1. **热点区域分析** - 识别案件高发区域
2. **团伙识别分析** - 发现潜在犯罪团伙
3. **作案模式分析** - 分析时间规律、案件类型、手法特征
4. **部署建议生成** - 生成巡逻、追踪、值班建议

返回结构：
```python
{
    "modules": { "hotspots", "gangs", "patterns", "deployment" },
    "summary": { "overall_risk_level", "risk_factors", "key_insights" },
    "priority_actions": [...],  # 优先行动建议
    "recommendations": [...]    # 综合建议
}
```
