# AiCommander v2.0 本地开发指南

本文件只用于本地开发和测试。服务器生产上线请使用
[生产部署手册](./docs/server-deployment-runbook.zh-CN.md)。

## 1. 环境要求

- Python 3.12
- Node.js 24 和 npm
- 可选：Docker Engine 或 Docker Desktop

生产数据库使用 PostgreSQL，后端测试和轻量本地开发可以使用 SQLite。

## 2. Docker 一键开发

Docker 正常运行后：

```bash
./start.sh
```

开发 Compose 会启动 PostgreSQL 14、Redis 7、后端、Celery 和前端，并启用源码挂载与
后端热重载。它只绑定本机回环地址，但仍使用开发密码，不能作为生产配置。

访问地址：

- 前端：<http://localhost:3000>
- 后端 API：<http://localhost:8000>
- 接口文档：<http://localhost:8000/docs>

首次打开页面时创建本地管理员：

```text
初始化令牌：dev-bootstrap-token-change-me
密码要求：至少 12 位
```

查看状态和日志：

```bash
docker compose ps
docker compose logs --tail=100 backend celery frontend
```

停止但保留开发数据：

```bash
./stop.sh
```

如需删除开发数据卷，先确认没有需要保留的数据，再单独处理。不要把清理开发卷的命令用于
生产环境。

## 3. SQLite 本地开发

### 3.1 后端

```bash
cd backend
python3.12 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-dev.txt
```

首次启动：

```bash
SECRET_KEY=local-development-secret-key-change-me \
BOOTSTRAP_TOKEN=local-bootstrap-token \
SESSION_COOKIE_SECURE=false \
ENABLE_API_DOCS=true \
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

默认数据库是 `backend/aicommander.db`。开发环境 `AUTO_CREATE_TABLES` 默认为 true；生产
环境强制关闭并使用 Alembic。

### 3.2 前端

另开终端：

```bash
cd frontend
npm ci
npm run dev
```

前端默认运行在 <http://localhost:3000>，并把 `/api` 和 WebSocket 代理到
`http://127.0.0.1:8000`。

首次打开页面时使用 `local-bootstrap-token` 创建本地管理员。

## 4. PostgreSQL 和 Redis 混合开发

只启动基础服务：

```bash
docker compose up -d postgres redis
```

本地后端连接开发容器：

```bash
cd backend
source venv/bin/activate

DATABASE_URL=postgresql://aicommander:aicommander-dev-only@127.0.0.1:5432/aicommander \
REDIS_URL=redis://127.0.0.1:6379/0 \
SECRET_KEY=local-development-secret-key-change-me \
BOOTSTRAP_TOKEN=local-bootstrap-token \
SESSION_COOKIE_SECURE=false \
ENABLE_API_DOCS=true \
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

当前开发 Compose 没有把 PostgreSQL 和 Redis 端口发布到宿主机。如确需混合开发，应在
本机专用 override 文件中绑定 `127.0.0.1`，不要修改生产 Compose，也不要绑定
`0.0.0.0`。

## 5. 运行测试

后端：

```bash
cd backend
source venv/bin/activate
python -m pytest
```

前端：

```bash
cd frontend
npm run typecheck
npm run test
npm run build
```

依赖审计：

```bash
cd frontend
npm audit

cd ../backend
python -m pip_audit
```

## 6. 数据库迁移开发

修改 SQLAlchemy 模型后应创建 Alembic 迁移，并在 SQLite 测试之外至少对真实
PostgreSQL 验证一次：

```bash
cd backend
alembic heads
alembic upgrade head
```

生产部署脚本会显式执行 `alembic upgrade head`，不会依赖应用自动建表。

## 7. 常见问题

### 页面要求初始化管理员

这是 v2.0 的正常行为。使用启动时设置的 `BOOTSTRAP_TOKEN` 创建首个管理员，初始化只允许
执行一次。

### 登录后立即回到登录页

本地 HTTP 开发必须设置 `SESSION_COOKIE_SECURE=false`。生产环境必须保持 true 并通过
HTTPS 访问。

### 前端无法连接后端

确认后端在 8000 端口运行，并检查：

```bash
curl -fsS http://127.0.0.1:8000/health/live
```

### Redis 未启动

SQLite 开发时部分同步功能仍可运行，但后台任务和生产就绪状态需要 Redis。生产环境中
Redis 不可用会让 `/health/ready` 返回 503。

### 忘记本地管理员密码

不要修改生产数据库。仅对可丢弃的本地开发环境，停止服务、备份需要的数据后重建开发库。
