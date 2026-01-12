# 环境配置完成总结

## ✅ 已完成的工作

1. **后端环境配置**
   - ✅ Python虚拟环境已创建
   - ✅ 所有Python依赖已安装（FastAPI, SQLAlchemy, LangChain等）
   - ✅ 代码问题已修复（metadata字段名冲突改为extra_data）

2. **启动脚本**
   - ✅ `backend/start_backend.sh` - 一键启动后端
   - ✅ `setup_database.sh` - 数据库设置脚本

## ⚠️ 当前问题

**Docker镜像拉取失败** - 由于网络证书验证问题，无法自动拉取PostgreSQL和Redis镜像。

## 🚀 解决方案

### 方案1：手动启动数据库（推荐）

在你的终端执行：

```bash
cd /Volumes/rin/AiCommander

# 尝试使用docker-compose（如果网络正常）
docker-compose up -d postgres redis

# 如果失败，检查Docker镜像是否已存在
docker images | grep -E "(postgres|redis)"
```

### 方案2：配置Docker镜像加速器

如果在中国大陆，可以配置镜像加速器：

```bash
# 编辑Docker配置
mkdir -p ~/.docker
cat > ~/.docker/daemon.json << EOF
{
  "registry-mirrors": [
    "https://docker.mirrors.ustc.edu.cn",
    "https://hub-mirror.c.163.com"
  ]
}
EOF

# 重启Docker/Colima
colima stop
colima start
```

### 方案3：使用本地PostgreSQL和Redis

```bash
# 安装
brew install postgresql@14 redis

# 启动
brew services start postgresql@14
brew services start redis

# 创建数据库
psql postgres
CREATE DATABASE aicommander;
CREATE USER aicommander WITH PASSWORD 'aicommander123';
GRANT ALL PRIVILEGES ON DATABASE aicommander TO aicommander;
\q
```

## 📋 启动步骤

一旦数据库启动成功，执行：

```bash
# 1. 初始化数据库
cd /Volumes/rin/AiCommander/backend
source venv/bin/activate
export DATABASE_URL=postgresql://aicommander:aicommander123@localhost:5432/aicommander
export REDIS_URL=redis://localhost:6379/0
python init_db.py

# 2. 启动后端
./start_backend.sh

# 或者手动启动
uvicorn app.main:app --reload
```

后端将在 http://localhost:8000 运行

## 📝 验证

访问以下URL确认服务正常：
- http://localhost:8000/health - 应该返回 `{"status": "healthy"}`
- http://localhost:8000/docs - API文档

