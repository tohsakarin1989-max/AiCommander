# AI案件分析系统

基于人工智能的案件分析系统，支持多AI模型协作决策（圆桌会议模式）。

## 功能特性

- 案件信息管理
- AI特征分析与关联分析
- 圆桌会议模式多AI协作决策
- 案件分析报告生成
- 巡逻防护建议生成
- AI模型配置管理

## 技术栈

### 后端
- Python 3.10+
- FastAPI
- PostgreSQL
- Redis
- Celery
- LangChain

### 前端
- React 18+
- TypeScript
- Ant Design
- ECharts

## 快速开始

### 一键启动（推荐）

运行交互式设置脚本：
```bash
./setup_local.sh
```

脚本会自动检测环境并提供启动选项。

### 环境要求
- Python 3.10+ ✅
- Node.js 18+ (可选，用于前端)
- Docker & Docker Compose（可选，用于PostgreSQL/Redis）
- **默认已内置 SQLite，无需额外数据库即可运行后端**

### 安装步骤

#### 方式一：使用Docker（推荐，最简单）

**前提：Docker Desktop 或 Colima 正在运行**

```bash
# 启动Docker（如果使用Colima）
colima start

# 启动所有服务
./start.sh
# 或
docker-compose up -d
```

访问系统：
- 前端: http://localhost:3000
- 后端API: http://localhost:8000
- API文档: http://localhost:8000/docs

停止服务：
```bash
./stop.sh
# 或
docker-compose down
```

#### 方式二：混合模式（推荐用于开发）

使用Docker运行 PostgreSQL/Redis，本地运行后端和前端（**如无法拉取镜像可跳过，直接使用内置 SQLite**）：

```bash
# 1. 启动数据库和Redis
docker-compose up -d postgres redis

# 2. 设置后端（新终端）
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql://aicommander:aicommander123@localhost:5432/aicommander
export REDIS_URL=redis://localhost:6379/0
python init_db.py
uvicorn app.main:app --reload

# 3. 启动前端（新终端）
cd frontend
npm install
npm run dev
```

#### 方式三：完全本地运行（仅用 SQLite）

不依赖外部数据库，直接使用内置 SQLite：

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 不设置 DATABASE_URL 环境变量（保持默认 sqlite:///./aicommander.db）
python init_db.py
uvicorn app.main:app --reload
```

前端仍然按方式二中的步骤3启动。

### 详细说明

更多启动选项和故障排除，请查看 [QUICKSTART.md](./QUICKSTART.md)

## 项目结构

```
AiCommander/
├── backend/          # 后端服务
├── frontend/         # 前端应用
├── docker-compose.yml
└── README.md
```

## 开发指南

详细开发指南请参考项目文档。

# AiCommander
## Ready for AI Review
