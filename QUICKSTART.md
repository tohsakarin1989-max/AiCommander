# 快速启动指南

## 方式一：使用Docker（推荐）

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
./start.sh

# 或者
docker-compose up -d
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

## 方式二：本地开发（不使用Docker）

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
export DATABASE_URL=postgresql://aicommander:aicommander123@localhost:5432/aicommander
export REDIS_URL=redis://localhost:6379/0
export SECRET_KEY=your-secret-key-change-in-production
```

3. **创建数据库**
```bash
# 连接到PostgreSQL
psql postgres

# 创建数据库和用户
CREATE DATABASE aicommander;
CREATE USER aicommander WITH PASSWORD 'aicommander123';
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
export DATABASE_URL=postgresql://aicommander:aicommander123@localhost:5432/aicommander
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

