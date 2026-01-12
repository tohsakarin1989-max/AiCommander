# 环境配置状态

## ✅ 已完成

1. **后端环境**
   - ✅ Python虚拟环境已创建 (`backend/venv`)
   - ✅ 核心依赖已安装（FastAPI, SQLAlchemy, LangChain等）
   - ✅ psycopg2-binary已安装
   - ✅ 代码问题已修复（metadata字段名冲突）

2. **启动脚本**
   - ✅ `backend/start_backend.sh` - 后端启动脚本
   - ✅ `setup_database.sh` - 数据库设置脚本

## ⚠️ 待完成

### 数据库和Redis启动

由于网络证书问题，Docker镜像无法自动拉取。请手动执行以下步骤：

#### 方法1：使用docker-compose（推荐）

```bash
cd /Volumes/rin/AiCommander
docker-compose up -d postgres redis
```

如果遇到网络问题，可以：
1. 检查网络连接
2. 配置Docker镜像加速器
3. 或使用方法2

#### 方法2：手动拉取镜像后启动

```bash
# 拉取镜像（可能需要配置镜像源）
docker pull postgres:14
docker pull redis:7-alpine

# 启动服务
cd /Volumes/rin/AiCommander
docker-compose up -d postgres redis
```

#### 方法3：使用本地PostgreSQL和Redis

```bash
# 安装PostgreSQL和Redis
brew install postgresql@14 redis

# 启动服务
brew services start postgresql@14
brew services start redis

# 创建数据库
psql postgres
CREATE DATABASE aicommander;
CREATE USER aicommander WITH PASSWORD 'aicommander123';
GRANT ALL PRIVILEGES ON DATABASE aicommander TO aicommander;
\q
```

## 🚀 启动后端

数据库启动后，执行：

```bash
cd /Volumes/rin/AiCommander/backend
./start_backend.sh
```

或者手动启动：

```bash
cd /Volumes/rin/AiCommander/backend
source venv/bin/activate
export DATABASE_URL=postgresql://aicommander:aicommander123@localhost:5432/aicommander
export REDIS_URL=redis://localhost:6379/0
python init_db.py
uvicorn app.main:app --reload
```

后端将在 http://localhost:8000 运行

## 📝 下一步

1. 解决Docker网络问题或使用本地数据库
2. 启动数据库和Redis
3. 运行 `backend/start_backend.sh` 启动后端
4. （可选）安装Node.js并启动前端

