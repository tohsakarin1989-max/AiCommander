# AiCommander

AI 驱动的案件分析系统，专注于涉油案件分析，采用"圆桌会议"模式实现多 AI 智能体协作研判。

## 技术栈

### 后端
- **框架**: FastAPI 0.104.1
- **数据库**: PostgreSQL 14 (生产) / SQLite (开发)
- **ORM**: SQLAlchemy 2.0.23
- **任务队列**: Celery 5.3.4 + Redis 7
- **AI/LLM**: LangChain 0.1.0, OpenAI SDK, Anthropic Claude SDK
- **向量数据库**: ChromaDB 0.4.22
- **嵌入模型**: Sentence Transformers 2.2.2

### 前端
- **框架**: React 18.2.0 + TypeScript 5.3.3
- **构建工具**: Vite 5.0.8
- **UI 库**: Ant Design 5.11.0
- **状态管理**: Zustand 4.4.7
- **数据请求**: @tanstack/react-query 5.12.0
- **图表**: ECharts 5.4.3

## 项目结构

```
AiCommander/
├── backend/                    # Python FastAPI 后端
│   └── app/
│       ├── main.py            # 应用入口
│       ├── config.py          # 配置管理
│       ├── database.py        # 数据库连接
│       ├── models/            # SQLAlchemy 数据模型
│       ├── api/               # API 路由
│       ├── services/          # 业务逻辑层
│       ├── repositories/      # 数据访问层
│       ├── ai/                # AI/LLM 核心逻辑
│       │   ├── agents/        # AI 智能体实现
│       │   ├── meeting_manager.py  # 圆桌会议管理
│       │   └── model_factory.py    # LLM 工厂
│       ├── tasks/             # Celery 异步任务
│       └── utils/             # 工具函数
├── frontend/                   # React 前端
│   └── src/
│       ├── pages/             # 页面组件
│       ├── components/        # 公共组件
│       └── services/          # API 客户端
└── docker-compose.yml          # Docker 编排
```

## 核心模块

### AI 智能体系统
- `backend/app/ai/meeting_manager.py` - 圆桌会议协调器
- `backend/app/ai/agents/base_agent.py` - 智能体基类
- `backend/app/ai/agents/moderator.py` - 主持人智能体
- `backend/app/ai/agents/analyst.py` - 分析师智能体
- `backend/app/ai/model_factory.py` - LLM 模型工厂

### 案件管理
- `backend/app/models/case.py` - 案件数据模型（含涉油专用字段）
- `backend/app/services/case_service.py` - 案件业务逻辑
- `backend/app/api/cases.py` - 案件 API 端点
- `frontend/src/pages/Cases/` - 案件管理前端

### 地理分析
- `backend/app/services/geo_analysis_service.py` - 地理分析服务
- `backend/app/services/trajectory_service.py` - 轨迹分析
- `backend/app/services/map_mcp_service.py` - 高德地图 MCP 集成
- `frontend/src/pages/Cases/CasesMap.tsx` - 地图可视化

### 语义分析
- `backend/app/services/semantic_analysis_service.py` - 语义分析
- `backend/app/services/embedding_service.py` - 文本嵌入
- `backend/app/services/vector_db_service.py` - 向量数据库操作

## 常用命令

### 启动服务

```bash
# Docker 完整启动
./start.sh

# 或手动启动
docker-compose up -d

# 本地开发 - 后端
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 本地开发 - 前端
cd frontend
npm run dev
```

### 数据库

```bash
# 初始化数据库
cd backend
python init_db.py

# Alembic 迁移
alembic upgrade head
alembic revision --autogenerate -m "描述"
```

### 停止服务

```bash
./stop.sh
# 或
docker-compose down
```

## API 端点

- **后端 API**: http://localhost:8000
- **API 文档**: http://localhost:8000/docs
- **前端**: http://localhost:3000

## 关键配置

### 环境变量
- `DATABASE_URL` - 数据库连接串（默认 SQLite）
- `REDIS_URL` - Redis 地址
- `SECRET_KEY` - 认证密钥
- `OPENAI_API_KEY` - OpenAI API 密钥
- `ANTHROPIC_API_KEY` - Anthropic API 密钥
- `FRONTEND_URL` - 前端地址（CORS 配置）

### 配置文件
- `backend/app/config.py` - 后端配置（Pydantic Settings）
- `frontend/vite.config.ts` - 前端构建配置
- `docker-compose.yml` - Docker 服务编排

## 业务特性

### 涉油案件专用字段
- 油品类型：汽油/柴油/原油/润滑油
- 涉案数量与价值
- 设施类型：管线/油库/加油站/油罐车
- 安全等级评估
- 作案手法分类
- 嫌疑人角色：内部员工/司机/加油员

### 核心功能
1. **圆桌会议** - 多 AI 协作案件研判
2. **串案分析** - 时空关联案件识别
3. **热点分析** - 地理聚类与热点检测
4. **智能报告** - AI 生成分析报告
5. **巡防建议** - 自动生成防控建议

## 开发规范

### 后端
- 遵循 FastAPI 最佳实践
- 使用 Pydantic 进行数据验证
- 服务层与 API 层分离
- 异步优先，必要时使用 Celery

### 前端
- 使用 TypeScript 严格模式
- 组件使用函数式 + Hooks
- 使用 react-query 管理服务端状态
- 遵循 Ant Design 设计规范

## 相关文档

- `README.md` - 项目概述
- `QUICKSTART.md` - 快速开始指南
- `AGENTS.md` - 智能体文档
- `MAP_FEATURES_GUIDE.md` - 地图功能指南
- `MCP_INTEGRATION.md` - MCP 集成文档
