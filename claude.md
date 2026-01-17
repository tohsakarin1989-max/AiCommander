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
cd backend && source venv/bin/activate && pytest

# 运行单个测试文件
pytest backend/tests/test_case_service.py

# 运行单个测试函数
pytest backend/tests/test_case_service.py::test_case_number_generation_increments
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

## 编码规范

### 后端
- Python PEP 8，4 空格缩进
- 路由模块：`app/api/<domain>.py`
- 服务层：`app/services/<domain>_service.py`
- 环境变量全大写下划线命名

### 前端
- TypeScript 严格模式
- 组件文件 PascalCase（如 `CaseList.tsx`）
- API 调用封装在 `frontend/src/services`

### 测试
- 使用 pytest，测试文件放 `backend/tests/test_*.py`
- 优先使用内存 SQLite 隔离测试数据
- 新增 API 应至少覆盖成功和失败路径

## 业务领域

涉油案件专用字段：油品类型、涉案数量/价值、设施类型（管线/油库/加油站/油罐车）、安全等级、作案手法、嫌疑人角色
