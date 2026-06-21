# 快速启动指南

## 方式零：本地快速测试（最简单，推荐优先使用）

> 使用内置 SQLite，**无需 Docker、PostgreSQL、Redis**，适合快速开发和测试。

### 前提条件
- Python 3.10+
- Node.js 18+

### 步骤

**1. 启动后端**

```bash
cd backend

# 首次：创建虚拟环境并安装依赖
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 首次：初始化数据库（生成 aicommander.db）
python init_db.py

# 启动（指定本机生成的 SECRET_KEY，SQLite 为默认数据库）
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**2. 启动前端**（新开终端）

```bash
cd frontend
npm install  # 首次
npm run dev
```

### 访问地址
- 前端：http://localhost:5173
- 后端 API：http://localhost:8000
- API 文档：http://localhost:8000/docs

### 配置 AI 模型（可选）

在后端启动命令中添加 API Key：

```bash
SECRET_KEY="$SECRET_KEY" ANTHROPIC_API_KEY=<your-anthropic-api-key> uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# 或
SECRET_KEY="$SECRET_KEY" OPENAI_API_KEY=<your-openai-api-key> uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

也可创建 `backend/.env` 文件避免每次输入：

```bash
# backend/.env
SECRET_KEY=<generate-a-local-secret-key>
ANTHROPIC_API_KEY=<your-anthropic-api-key>
# OPENAI_API_KEY=<your-openai-api-key>
```

然后直接运行：

```bash
cd backend && source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 运行测试

```bash
cd backend && source venv/bin/activate

pytest                                              # 全部测试
pytest -v                                           # 详细输出
pytest tests/test_case_service.py                  # 单个文件
pytest tests/test_case_service.py::test_case_number_generation_increments  # 单个函数
```

测试文件一览：

| 文件 | 覆盖范围 |
|------|---------|
| `test_case_service.py` | 案件服务层逻辑 |
| `test_geo_analysis.py` | 地理分析（热点、距离计算） |
| `test_meeting_manager.py` | 圆桌会议流程 |
| `test_analyst_prompts.py` | 分析师 Prompt 生成 |
| `test_moderator_prompts.py` | 主持人 Prompt 生成 |

> 所有测试使用内存 SQLite，无需外部数据库或 Redis。

---

## 方式一：使用Docker（推荐生产/集成测试）

### 前提条件
1. Docker Desktop 已安装并运行
2. 如果使用Colima，需要先启动：
```bash
colima start
```

### 启动步骤

1. **启动Docker服务**
```bash
# 如果使用Colima
colima start

# 或者启动Docker Desktop应用
```

2. **启动所有服务**
```bash
# 首次需要先添加执行权限
chmod +x start.sh stop.sh

./start.sh
```

3. **查看服务状态**
```bash
docker-compose ps
```

4. **查看日志**
```bash
# 查看所有服务日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f backend
docker-compose logs -f frontend
```

5. **访问系统**
- 前端: http://localhost:3000
- 后端API: http://localhost:8000
- API文档: http://localhost:8000/docs

6. **停止服务**
```bash
./stop.sh

# 或者
docker-compose down
```

---

## 方式二：本地开发（PostgreSQL + Redis，不使用Docker）

### 前提条件
1. Python 3.10+ ✅ (已安装: 3.13.4)
2. Node.js 18+ (需要安装)
3. PostgreSQL 14+ (需要安装或使用Docker仅运行数据库)
4. Redis 7+ (需要安装或使用Docker仅运行Redis)

### 安装Node.js

**使用Homebrew:**
```bash
brew install node
```

**或下载安装包:**
访问 https://nodejs.org/ 下载安装

### 安装PostgreSQL和Redis

**使用Homebrew:**
```bash
brew install postgresql@14 redis
```

**或仅使用Docker运行数据库:**
```bash
# 只启动数据库和Redis
docker-compose up -d postgres redis
```

### 启动步骤

1. **启动数据库和Redis**（如果本地安装）
```bash
# PostgreSQL
brew services start postgresql@14

# Redis
brew services start redis
```

2. **设置环境变量**
```bash
export DB_PASSWORD=<your-local-database-password>
export DATABASE_URL="postgresql://aicommander:${DB_PASSWORD}@localhost:5432/aicommander"
export REDIS_URL=redis://localhost:6379/0
export SECRET_KEY=<generate-a-local-secret-key>
```

3. **创建数据库**
```bash
# 连接到PostgreSQL
psql postgres

# 创建数据库和用户
CREATE DATABASE aicommander;
CREATE USER aicommander WITH PASSWORD '<choose-a-local-database-password>';
GRANT ALL PRIVILEGES ON DATABASE aicommander TO aicommander;
\q
```

4. **启动后端**

```bash
cd backend

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 初始化数据库
python init_db.py

# 启动服务
uvicorn app.main:app --reload
```

后端将在 http://localhost:8000 运行

5. **启动前端**（新开一个终端）

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端将在 http://localhost:3000 运行

---

## 方式三：混合模式（推荐用于开发）

使用Docker运行数据库和Redis，本地运行后端和前端：

1. **启动数据库和Redis**
```bash
docker-compose up -d postgres redis
```

2. **设置环境变量并启动后端**
```bash
export DB_PASSWORD=<your-local-database-password>
export DATABASE_URL="postgresql://aicommander:${DB_PASSWORD}@localhost:5432/aicommander"
export REDIS_URL=redis://localhost:6379/0

cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python init_db.py
uvicorn app.main:app --reload
```

3. **启动前端**（新开终端）
```bash
cd frontend
npm install
npm run dev
```

---

## 常见问题

### Docker无法连接
```bash
# 检查Docker状态
docker info

# 如果使用Colima
colima status
colima start
```

### 端口被占用
```bash
# 检查端口占用
lsof -i :8000  # 后端
lsof -i :3000  # 前端
lsof -i :5432  # PostgreSQL
lsof -i :6379  # Redis

# 停止占用端口的进程或修改docker-compose.yml中的端口
```

### 数据库连接失败
- 检查PostgreSQL是否运行
- 检查数据库用户名和密码
- 检查DATABASE_URL环境变量

### 前端无法连接后端
- 检查后端是否运行在8000端口
- 检查vite.config.ts中的proxy配置
- 查看浏览器控制台错误
