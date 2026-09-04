# AICommander v2.0.2-stable 服务器部署与运维手册

> 初次生产链路核验：2026-08-14；部署加固回归：2026-09-04
> 适用版本：AICommander 2.0.2-stable
> 推荐环境：单台 Ubuntu Server 24.04 LTS、Docker Engine、Docker Compose Plugin
> 系统边界：涉油案件数智研判与防控辅助系统，生产环境默认部署在单位内网或 VPN 后

> Agent Lab 默认关闭，独立启停且不参与核心就绪判定；启用、验收和紧急关闭步骤见
> [“油盾·双域研判智能体”部署、运行与验收手册](./agent-lab-runbook.zh-CN.md)。

## 1. 当前可部署性结论

v2.0.2-stable 已作为前期测试部署的稳定代码基线。生产容器链路已经在干净的
PostgreSQL 16 和 Redis 7 环境中完成隔离启动、冒烟与备份恢复验收。正式业务上线前仍需
在目标服务器完成域名、HTTPS、备份恢复记录、单位网络策略和业务人员验收；这些现场工作
依赖目标服务器，不能由源码仓库的自动化结果代替。

### 1.1 2026-08-14 已完成的验证

| 检查项 | 结果 |
| --- | --- |
| Python 版本 | Python 3.12.12 干净虚拟环境 |
| 后端测试 | 167 项全部通过 |
| 前端测试 | 17 个测试文件、69 项全部通过 |
| TypeScript 类型检查 | 通过 |
| 前端生产构建 | Vite 8.2.1 构建通过 |
| 前端生产依赖审计 | `npm audit`，0 个已知漏洞 |
| Python 完整依赖审计 | `pip-audit`，0 个已知漏洞 |
| PostgreSQL 空库迁移 | Alembic 全链路成功，最终 35 张业务表 |
| SQLite 数据迁移实测 | 31 张源表、998 行，188 起案件完整迁入 PostgreSQL |
| 敏感配置迁移 | 旧密钥解密、新密钥重新加密通过 |
| 生产容器 | PostgreSQL、Redis、后端、Celery、前端共 5 个服务正常 |
| 网络暴露 | 仅前端绑定 `127.0.0.1`，8000/5432/6379 均未发布 |
| 健康检查 | `/health/ready` 返回 PostgreSQL、Redis 和数据库迁移版本均为 `ok` |
| 登录权限 | 首次初始化、管理员、分析员、只读账号、锁定、退出均已验证 |
| WebSocket | 匿名连接被拒绝，登录会话可正常接收大屏数据 |
| 浏览器验收 | 登录页、业务首页、真实数据、桌面和手机宽度均已检查 |
| 生产接口文档 | `/docs`、`/redoc`、`/openapi.json` 均返回 404 |

实测迁移源文件 SHA-256 为：

```text
bb919925364df9bf698cb8d9af2d160a17d7f857b7d58a5d9384a503d2ef9487
```

该值只用于识别本次测试样本。正式迁移前如果本地数据继续变化，哈希和行数也应变化，
以正式迁移报告为准。

### 1.2 v2.0 的生产保护

- 所有业务 `/api` 和 WebSocket 默认要求登录。
- 角色分为管理员、分析员、只读账号；只读账号不能写入，配置、模型、用户和部署接口仅管理员可用。
- 连续 5 次登录失败后账号锁定 15 分钟。
- 浏览器使用 `HttpOnly`、`Secure`、`SameSite=Strict` 会话 Cookie。
- 写操作检查来源并记录审计日志。
- AI 模型和系统配置密钥加密入库，查询只返回掩码。
- 生产环境拒绝 SQLite、无密码 Redis、HTTP 前端地址、通配主机名、开放接口文档、
  弱密钥、关闭认证和自动建表。
- 部署前检查域名、端口、版本、密钥长度与文件权限，并在新镜像中再次校验应用配置。
- 数据库迁移前自动生成 PostgreSQL 备份、版本清单和 SHA-256 校验文件。
- `/health/ready` 同时检查数据库连接、Redis 和 Alembic 当前迁移版本。
- PostgreSQL 和 Redis 仅在 Docker 内部网络通信，Redis 已启用密码和 AOF。
- 后端容器只读运行、非 root 用户、移除 Linux capabilities，并禁止权限提升。
- 镜像基础层使用固定 digest，日志启用大小和数量轮转。
- 当前生产镜像关闭本地 Chroma 向量库，规避其未修复依赖风险；案件、图谱、报告和结构化研判不受影响。

## 2. 推荐部署架构

```text
用户浏览器
    |
    | HTTPS 443
    v
宿主机 Nginx
    |
    | HTTP 127.0.0.1:3000
    v
前端 Nginx 容器
    |-- 静态前端
    |-- /api 和 WebSocket --> FastAPI 后端容器:8000
                              |-- PostgreSQL 16
                              |-- Redis 7
                              `-- Celery Worker
```

宿主机只开放：

- `22/tcp`：仅管理员固定 IP 或运维 VPN。
- `80/tcp`：证书签发和跳转 HTTPS；纯内网使用单位 CA 时可按制度关闭。
- `443/tcp`：系统访问入口。

不要开放：

- `3000/tcp`：只绑定 `127.0.0.1`，供宿主机 Nginx 使用。
- `8000/tcp`：后端只在 Docker 内部网络可见。
- `5432/tcp`：PostgreSQL 只在 Docker 内部网络可见。
- `6379/tcp`：Redis 只在 Docker 内部网络可见。

## 3. 服务器规格

| 场景 | CPU | 内存 | 系统盘/数据盘 | 说明 |
| --- | ---: | ---: | ---: | --- |
| 测试服务器 | 4 核 | 8 GB | 80 GB SSD | 少量并发、模型调用走外部 API |
| 单机生产建议 | 8 核 | 16 GB | 160 GB SSD | 适合当前单后端 worker 架构 |
| 数据量或并发增长 | 16 核 | 32 GB | 300 GB SSD | 需同步做压测和数据库监控 |

至少为 `/var/lib/docker`、`/opt/aicommander/backups` 和系统日志预留空间。模型 API
响应速度主要取决于外部网络；如部署在断网内网，应另行接入单位内部模型服务。

## 4. 需要安装的组件和官方下载位置

宿主机不需要安装 Python、Node.js、PostgreSQL 或 Redis，它们由容器提供。

| 组件 | 用途 | 安装位置 | 官方来源 |
| --- | --- | --- | --- |
| Ubuntu Server 24.04 LTS | 宿主操作系统 | 服务器系统盘 | [Ubuntu Server 下载](https://ubuntu.com/download/server) |
| Git | 获取受控发布代码 | Ubuntu APT | [Git 下载说明](https://git-scm.com/download/linux) |
| Docker Engine | 容器运行时 | Docker 官方 APT | [Ubuntu 安装文档](https://docs.docker.com/engine/install/ubuntu/) |
| Docker Compose Plugin | 编排 5 个服务 | 随 Docker APT 安装 | [Linux Compose 文档](https://docs.docker.com/compose/install/linux/) |
| Nginx | HTTPS 入口 | Ubuntu APT | [Nginx 官方包](https://nginx.org/en/linux_packages.html) |
| Certbot | 公网 Let's Encrypt 证书 | Snap | [Certbot Nginx 指引](https://certbot.eff.org/instructions?ws=nginx&os=snap) |
| PostgreSQL 16 镜像 | 业务数据库 | Docker 数据卷 | [PostgreSQL 官方镜像](https://hub.docker.com/_/postgres) |
| Redis 7 镜像 | 缓存和 Celery 队列 | Docker 数据卷 | [Redis 官方镜像](https://hub.docker.com/_/redis) |

仓库已固定以下运行基础镜像和 digest：

- Python 3.12 slim：后端和 Celery。
- Node 24 alpine：仅前端构建阶段。
- Nginx 1.28 alpine：前端运行阶段。
- PostgreSQL 16 alpine：业务数据库。
- Redis 7 alpine：缓存和后台任务队列。

只从上述官方站点、Ubuntu 官方仓库或单位批准的软件源获取软件。不要使用不明网盘中的
Docker、数据库或证书工具安装包。

## 5. 安装 Ubuntu 基础环境

以下命令适用于 Ubuntu Server 24.04 LTS。先启用 OpenSSH，并确保已准备一个可用的
管理员账号。

```bash
sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y ca-certificates curl git nginx ufw openssl sqlite3 snapd
sudo systemctl enable --now nginx
```

安装 Docker 官方版本。先删除可能冲突的发行版包：

```bash
sudo apt-get remove -y docker.io docker-compose docker-compose-v2 docker-doc podman-docker containerd runc
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

添加 Docker 官方 APT 源：

```bash
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
```

安装并检查：

```bash
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
sudo docker version
sudo docker compose version
```

项目脚本直接调用 `docker`。推荐使用 `sudo ./scripts/...` 执行生产脚本。不要为了方便
随意把普通业务账号加入 `docker` 组；该组可以控制宿主机容器，权限接近 root。

## 6. 配置防火墙、DNS 和时间

把 `ADMIN_IP` 替换为运维人员固定出口 IP。启用 UFW 前先保留一个已登录 SSH 会话，
防止规则错误导致失联。

```bash
sudo timedatectl set-timezone Asia/Shanghai
timedatectl status

sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from ADMIN_IP to any port 22 proto tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status verbose
```

注意 Docker 发布端口可能绕过 UFW。项目的生产 Compose 已从结构上阻止 5432、6379、
8000 对宿主机发布，3000 也只绑定回环地址。

DNS 需要提前创建：

```text
aicommander.example.org  A  <服务器 IPv4>
```

内网部署可使用内部 DNS 名称，但 `APP_DOMAIN`、Nginx `server_name`、证书名称必须一致。

## 7. 准备发布代码

生产服务器应使用已评审的 Git 标签或固定提交，不要直接复制开发目录中的临时文件。
本版本发布后应固定使用 `v2.0.2-stable` 标签，不要从开发分支直接部署：

```bash
sudo install -d -m 0750 -o "$USER" -g "$USER" /opt/aicommander
git clone --branch v2.0.2-stable --depth 1 <代码仓库地址> /opt/aicommander
cd /opt/aicommander
test "$(cat VERSION)" = "2.0.2-stable"
git status --short
git rev-parse HEAD
chmod 0755 scripts/*.sh backend/docker-entrypoint.sh
```

如标签尚未同步到单位代码源，应先校验发布提交哈希和签发记录。不要临时改用分支头，
也不要直接执行未经检查的 `git add -A`，尤其要排除 `.env.production`、`secrets/`、
`backups/` 和数据库。

## 8. 初始化生产配置和密钥

进入项目目录执行：

```bash
cd /opt/aicommander
./scripts/init-production.sh
```

脚本会创建：

```text
.env.production
secrets/db_password
secrets/redis_password
secrets/secret_key
secrets/bootstrap_token
```

权限应为：

```bash
stat -c '%a %n' .env.production secrets secrets/*
```

预期 `.env.production` 和四个密钥文件为 `600`，`secrets` 目录为 `700`。编辑配置：

```bash
nano .env.production
```

最小配置示例：

```dotenv
APP_DOMAIN=aicommander.example.org
APP_PORT=3000
APP_VERSION=2.0.2-stable
SECRETS_DIR=./secrets
BACKUP_DIR=./backups/postgres
ENABLE_BONUS_ACCOUNTING=false
ACCESS_TOKEN_EXPIRE_MINUTES=480
CELERY_CONCURRENCY=2
ENABLE_AGENT_LAB=false
AGENT_MODE=off
AGENT_MUTATIONS_ENABLED=false
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `APP_DOMAIN` | 用户实际访问的域名，不带协议和路径 |
| `APP_PORT` | 宿主机回环端口，默认 3000；不能绑定公网地址 |
| `APP_VERSION` | 生产镜像标签，和发布版本一致 |
| `SECRETS_DIR` | 四个 Docker secret 文件的位置 |
| `BACKUP_DIR` | 部署前数据库备份目录，默认 `./backups/postgres` |
| `ENABLE_BONUS_ACCOUNTING` | 是否显示内部奖金核算模块，默认关闭 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 登录有效期，默认 480 分钟 |
| `CELERY_CONCURRENCY` | 后台任务并发，8 GB 内存建议 2 |

四个密钥不要写入 `.env.production`：

- `db_password`：PostgreSQL 密码。
- `redis_password`：Redis 密码。
- `secret_key`：会话签名和配置加密主密钥，部署后必须保持稳定。
- `bootstrap_token`：首次管理员初始化令牌，只在尚无用户时有效。

立即把 `.env.production` 和 `secrets` 做加密离线备份。丢失 `secret_key` 会导致已有会话
失效且加密的模型密钥无法解密，不能通过重新生成来恢复。

## 9. 全新系统首次部署

如果不需要迁移旧 SQLite 数据，直接执行：

```bash
cd /opt/aicommander
sudo ./scripts/deploy-production.sh
```

脚本会依次完成：

1. 运行生产预检，校验域名、端口、版本、密钥长度、文件权限和 Compose 配置。
2. 拉取固定基础镜像并构建前后端镜像。
3. 在新后端镜像中校验生产应用配置。
4. 启动 PostgreSQL 和 Redis，并等待两个服务健康。
5. 自动在 `BACKUP_DIR` 生成数据库升级前备份、清单和 SHA-256 校验文件。
6. 执行 `alembic upgrade head`。
7. 启动后端、Celery 和前端。
8. 等待 `/health/ready` 成功；数据库迁移版本落后时不会进入就绪状态。

检查服务：

```bash
sudo docker compose --env-file .env.production \
  -f docker-compose.production.yml ps
curl -fsS http://127.0.0.1:3000/health/live
curl -fsS http://127.0.0.1:3000/health/ready
```

五个服务应为运行或健康状态，`ready` 返回的 `database`、`schema` 和 `redis` 都应为
`ok`，并返回 `version=2.0.2-stable`。随后执行自动验收：

```bash
sudo ./scripts/verify-test-deployment.sh
```

脚本同时验证前端安全响应头、运行版本、Agent 关闭态、匿名业务接口为 401，以及
`/docs`、`/redoc`、`/openapi.json` 均为 404。默认把响应和
`verification.manifest` 写入 `backups/deployment-evidence/<时间>/`；该目录不得包含
会话 Cookie、初始化令牌或任何业务样本。

## 10. 迁移现有 SQLite 业务数据

现有数据不能只复制 `aicommander.db` 到服务器，也不能对 SQLite 直接执行 PostgreSQL
迁移。仓库已经提供受控迁移工具，会保留主键、重置序列、处理会议与报告的循环外键，
并用新生产密钥重新加密模型和系统配置密钥。

### 10.1 停止写入并备份

在旧系统停止案件录入和后台任务后执行：

```bash
mkdir -p backups/source
cp backend/aicommander.db \
  backups/source/aicommander-before-v2.db
chmod 0600 backups/source/aicommander-before-v2.db
sha256sum backups/source/aicommander-before-v2.db
sqlite3 backups/source/aicommander-before-v2.db 'PRAGMA integrity_check;'
```

完整性检查必须输出 `ok`。

### 10.2 准备旧系统 SECRET_KEY

迁移工具需要旧系统用于加密 API Key 的 `SECRET_KEY`。创建一个只包含原始值的文件，
不要写成 `SECRET_KEY=...`：

```bash
install -m 600 /dev/null backups/source/old-secret-key
nano backups/source/old-secret-key
```

如果旧系统没有保存该值，已加密的旧模型密钥无法恢复。不要猜测或用新密钥替代。

### 10.3 初始化新生产配置并执行迁移

先完成第 8 节，再确认目标 PostgreSQL 是空库。然后执行：

```bash
cd /opt/aicommander
sudo ./scripts/migrate-production-data.sh \
  /绝对路径/aicommander-before-v2.db \
  /绝对路径/old-secret-key
```

迁移报告生成在：

```text
backups/migration/sqlite-to-postgres-report.json
```

检查报告中的：

- 源文件 SHA-256 与手工计算一致。
- 各表 `source_count` 和 `target_count` 一致。
- `cases` 数量符合停机时记录。
- 序列已重置。
- 会议最终报告引用已恢复。
- 敏感配置已重新加密。

当前样本实测迁移了 31 张源表、998 行数据，其中案件 188 起。正式库如果发生更新，
数量应以停写后的正式备份为准。

迁移成功后再启动全部服务：

```bash
sudo ./scripts/deploy-production.sh
```

在业务切换前至少抽查 20 起案件，核对案件编号、时间、地点、人员车辆、佐证材料、报告、
会议和结论。迁移失败时不要反复写入同一目标库；保留报告和日志，清理测试目标后重新执行。

## 11. 配置宿主机 Nginx

项目提供样例：`deploy/nginx/aicommander.conf.example`。复制并替换域名：

```bash
sudo cp deploy/nginx/aicommander.conf.example \
  /etc/nginx/sites-available/aicommander
sudo sed -i 's/aicommander.example.org/实际域名/g' \
  /etc/nginx/sites-available/aicommander
sudo ln -s /etc/nginx/sites-available/aicommander \
  /etc/nginx/sites-enabled/aicommander
sudo nginx -t
sudo systemctl reload nginx
```

如果把 `APP_PORT` 改为非 3000，必须同步修改配置中的 `127.0.0.1:3000`。

上线前从服务器确认：

```bash
curl -fsSI http://127.0.0.1:3000/
curl -fsSI http://实际域名/
```

## 12. 配置 HTTPS

### 12.1 公网域名使用 Let's Encrypt

只有域名已解析到服务器，且公网能访问 80 端口时才能使用 HTTP 验证。

```bash
sudo snap install core
sudo snap refresh core
sudo snap install --classic certbot
sudo ln -s /snap/bin/certbot /usr/local/bin/certbot
sudo certbot --nginx -d aicommander.example.org
sudo certbot renew --dry-run
systemctl list-timers | grep certbot
```

Certbot 会修改 Nginx 配置并建立 HTTP 到 HTTPS 跳转。完成后检查：

```bash
curl -fsSI https://aicommander.example.org/
curl -fsS https://aicommander.example.org/health/ready
```

### 12.2 内网域名使用单位 CA

向单位证书管理部门申请包含实际域名的证书和私钥，限制私钥权限为 `600`。在 Nginx
对应 `server` 中配置 `listen 443 ssl http2`、`ssl_certificate` 和
`ssl_certificate_key`，再将 80 端口跳转至 HTTPS。客户端必须信任单位根证书。

生产登录 Cookie 强制使用 Secure，因此不要把纯 HTTP 当作正式访问方式。

## 13. 首次管理员初始化

HTTPS 生效后首次打开系统，页面会显示“初始化系统管理员”。在服务器本地读取一次性令牌：

```bash
sudo cat /opt/aicommander/secrets/bootstrap_token
```

在页面中输入：

1. 一次性初始化令牌。
2. 管理员显示名称。
3. 管理员用户名。
4. 至少 12 位的强密码和确认密码。

首个管理员创建后，初始化接口会拒绝再次创建。不要通过聊天、邮件或截图传递初始化令牌。
管理员登录后进入“设置 -> 用户管理”创建其他账号。

角色边界：

| 角色 | 权限 |
| --- | --- |
| 管理员 | 全部业务读写、用户、模型、系统配置和部署管理 |
| 分析员 | 业务读写和研判，不可管理用户、模型、配置和部署 |
| 只读账号 | 仅查看业务数据，所有写操作被拒绝 |

系统禁止停用或降级最后一个有效管理员。

## 14. AI 模型和地图配置

管理员在系统设置中录入模型 API Key。Key 会在服务端加密后写入 PostgreSQL，接口只返回
掩码。不要把 Key 写入代码、Git、Dockerfile 或前端环境变量。

地图默认使用 OpenStreetMap，不要求 API Key。若改用第三方地图，除系统加密保存外，
还应在供应商控制台设置域名、IP、配额和账单告警。

生产镜像暂时关闭 Chroma 本地向量库。依赖向量库的语义检索能力不应作为当前上线验收
硬指标；结构化筛选、时空分析、图谱、报告和模型研判可以正常运行。

## 15. 上线验收清单

### 15.1 容器和网络

```bash
sudo docker compose --env-file .env.production \
  -f docker-compose.production.yml ps
sudo ss -lntp
curl -fsS https://实际域名/health/live
curl -fsS https://实际域名/health/ready
```

确认：

- [ ] 只有 22、80、443 对外监听。
- [ ] 3000 只在 `127.0.0.1` 监听。
- [ ] 8000、5432、6379 未在宿主机监听。
- [ ] PostgreSQL、Redis、后端和前端均健康，Celery 正常运行。
- [ ] `/docs`、`/redoc`、`/openapi.json` 均返回 404。

### 15.2 身份和安全

- [ ] 未登录访问案件 API 返回 401。
- [ ] 错误初始化令牌返回 403，初始化完成后重复初始化返回 409。
- [ ] 管理员可以管理用户和模型配置。
- [ ] 分析员访问管理员接口返回 403。
- [ ] 只读账号读取正常，新增、修改、删除返回 403。
- [ ] 退出后原会话不能继续使用。
- [ ] 浏览器 Cookie 具有 Secure、HttpOnly、SameSite=Strict。
- [ ] 页面响应包含 CSP、HSTS、X-Frame-Options 和 nosniff。

### 15.3 业务验收

- [ ] 案件列表、详情、搜索和分页正常。
- [ ] 新增案件和保存前预检正常。
- [ ] 批量导入先预览再提交，错误行可定位。
- [ ] 批量复核和待办分流正常。
- [ ] 案件研判、图谱、时空分析和地图可打开。
- [ ] 报告生成、复核和导出正常。
- [ ] AI 模型连通测试成功，失败时有明确提示。
- [ ] 大屏 WebSocket 登录后能接收数据，匿名连接被拒绝。
- [ ] 现有 SQLite 迁移数据按报告和抽样核对无误。

## 16. 日常运维命令

```bash
cd /opt/aicommander

# 状态
sudo docker compose --env-file .env.production \
  -f docker-compose.production.yml ps

# 最近日志
sudo docker compose --env-file .env.production \
  -f docker-compose.production.yml logs --tail=200 backend celery frontend postgres redis

# 持续查看后端日志
sudo docker compose --env-file .env.production \
  -f docker-compose.production.yml logs -f --tail=100 backend

# 重启单个服务
sudo docker compose --env-file .env.production \
  -f docker-compose.production.yml restart backend

# 停止应用但保留数据卷
sudo docker compose --env-file .env.production \
  -f docker-compose.production.yml down

# 再次启动
sudo docker compose --env-file .env.production \
  -f docker-compose.production.yml up -d
```

不要执行 `down -v`，它会删除 PostgreSQL 和 Redis 数据卷。

## 17. PostgreSQL 备份和恢复

PostgreSQL 是业务主数据。至少每日一次完整备份，并把备份加密复制到服务器之外。
[PostgreSQL 官方 pg_dump 文档](https://www.postgresql.org/docs/16/app-pgdump.html)。

### 17.1 备份

```bash
cd /opt/aicommander
sudo ./scripts/backup-production.sh
```

脚本会生成 PostgreSQL custom-format 备份、版本清单和同名 `.sha256` 文件。每次执行
`deploy-production.sh` 也会在 Alembic 升级前自动调用该脚本；备份失败时部署立即停止。
备份脚本不会自动删除旧文件，避免错误保留策略造成数据丢失。

建议策略：保留最近 7 个每日备份、4 个每周备份、12 个每月备份，并至少每天把一份复制
到异机或受控备份存储。只有实际恢复演练成功，备份才算可用。

### 17.2 非破坏性恢复验证（每次测试部署必做）

先创建一次迁移后的新备份，再把该备份恢复到临时数据库。脚本验证 SHA-256、恢复过程、
表数量和 Alembic 版本后会删除临时数据库，不停止服务，也不覆盖当前业务库：

```bash
cd /opt/aicommander
sudo ./scripts/backup-production.sh
sudo ./scripts/verify-backup-restore.sh
```

通过后会在备份旁生成同名 `.restore-verified` 证据文件。必须把备份、`.sha256`、
`.manifest` 和 `.restore-verified` 一并复制到受控的异机存储。若要验证指定备份：

```bash
sudo BACKUP_FILE=/opt/aicommander/backups/postgres/指定备份.dump \
  ./scripts/verify-backup-restore.sh
```

### 17.3 灾难恢复（会覆盖业务库）

以下流程会覆盖当前数据库，只允许在已审批的维护窗口或独立测试服务器执行：

```bash
cd /opt/aicommander
sudo docker compose --env-file .env.production \
  -f docker-compose.production.yml stop frontend backend celery

sudo docker compose --env-file .env.production \
  -f docker-compose.production.yml exec -T postgres \
  pg_restore -U aicommander -d postgres --clean --if-exists --create \
  < backups/postgres/指定备份.dump

sudo docker compose --env-file .env.production \
  -f docker-compose.production.yml up -d
curl -fsS http://127.0.0.1:3000/health/ready
```

恢复后核对案件数、用户、模型配置和抽样业务记录。首次灾难恢复演练应在独立测试服务器进行。

## 18. Redis 和密钥备份

Redis 主要保存缓存和任务状态，PostgreSQL 才是业务事实源。Redis 已开启 AOF，
仍可定期生成 RDB 快照。参考 [Redis 持久化文档](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)。

```bash
sudo docker compose --env-file .env.production \
  -f docker-compose.production.yml exec -T redis sh -c \
  'redis-cli --no-auth-warning -a "$(cat /run/secrets/redis_password)" SAVE'
```

`.env.production` 和 `secrets/` 必须单独做加密离线备份：

```bash
cd /opt/aicommander
sudo tar -czf /安全临时位置/aicommander-config-secrets.tar.gz \
  .env.production secrets
sudo chmod 0600 /安全临时位置/aicommander-config-secrets.tar.gz
```

随后使用单位批准的加密介质或密码管理系统保存，并删除未加密临时副本。不要把密钥压缩包
与数据库备份长期放在同一台服务器。

## 19. 版本升级和回滚

升级前必须备份 PostgreSQL、配置和密钥，并记录当前提交号和镜像 ID：

```bash
git rev-parse HEAD
sudo docker images --digests | grep aicommander
```

升级流程：

```bash
cd /opt/aicommander
git fetch --tags
git checkout <已验收的新标签>
sudo ./scripts/deploy-production.sh
```

部署脚本会先完成预检和镜像内配置校验，再启动数据服务并创建升级前备份；只有备份成功
才执行 Alembic 升级，最后启动全部服务并检查数据库连接、Redis 和迁移版本就绪状态。

应用代码回滚可以切回上一标签重新构建；数据库不能只靠切换 Git 回滚。若新迁移不向后兼容：

1. 停止前端、后端和 Celery。
2. 切回上一发布标签。
3. 恢复升级前 PostgreSQL 备份。
4. 重新构建和启动上一版本。
5. 完成健康和业务抽查后恢复访问。

不要在没有单独验证的情况下直接执行 `alembic downgrade`。

## 20. 内网离线部署

在与目标服务器相同 CPU 架构的联网 Linux 机器上构建并导出：

```bash
sudo docker compose --env-file .env.production \
  -f docker-compose.production.yml build --pull
sudo docker pull postgres:16-alpine@sha256:44c4ee9810eff91f7eab4d822642e01115b1a9eccce4bcbdde7604752d68eac6
sudo docker pull redis:7-alpine@sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2
sudo docker save -o aicommander-v2-images.tar \
  aicommander-backend:2.0.2-stable \
  aicommander-frontend:2.0.2-stable \
  postgres:16-alpine \
  redis:7-alpine
sha256sum aicommander-v2-images.tar
```

通过单位批准介质传入服务器后：

```bash
sha256sum -c aicommander-v2-images.tar.sha256
sudo docker load -i aicommander-v2-images.tar
```

离线部署时不要运行带 `--pull` 的构建。建议由联网区完成镜像漏洞扫描，再连同扫描报告、
镜像哈希、源码标签和部署手册一起交付。

## 21. 常见故障排查

### 21.1 `/health/ready` 返回 503

```bash
sudo docker compose --env-file .env.production \
  -f docker-compose.production.yml ps
sudo docker compose --env-file .env.production \
  -f docker-compose.production.yml logs --tail=200 backend postgres redis
```

重点检查磁盘空间、密钥文件权限、PostgreSQL 健康检查和 Redis 密码是否一致。

### 21.2 浏览器能打开但无法登录

- 确认通过 HTTPS 访问，生产 Cookie 不支持正式纯 HTTP 使用。
- 检查 `APP_DOMAIN` 与浏览器域名是否完全一致。
- 检查 Nginx 是否传递 `Host`、`X-Forwarded-Proto` 和 WebSocket Upgrade 头。
- 连续输错 5 次会锁定 15 分钟，应等待或由管理员处理账号。

### 21.3 页面空白或接口被 CSP 阻断

必须使用 v2.0 最新前端镜像。重新构建并只替换前端：

```bash
sudo docker compose --env-file .env.production \
  -f docker-compose.production.yml build frontend
sudo docker compose --env-file .env.production \
  -f docker-compose.production.yml up -d --no-deps frontend
```

不要自行改成跨域 API 地址，前端应始终使用同源 `/api`。

### 21.4 WebSocket 连接失败

检查宿主机和容器内两层 Nginx 的 `Upgrade`、`Connection` 头；同时确认浏览器已经登录，
匿名 WebSocket 被拒绝是正常安全行为。

### 21.5 模型调用失败

- 在管理员设置中执行模型连通测试。
- 检查服务器是否能访问模型供应商域名和 443 端口。
- 检查供应商额度、区域限制、IP 白名单和代理。
- 不要在日志或工单中粘贴完整 API Key。

### 21.6 磁盘空间不足

```bash
df -h
sudo docker system df
sudo du -sh /var/lib/docker /opt/aicommander/backups
```

先转移旧备份并按保留策略清理。不要直接删除 Docker volume，也不要执行未经确认的
`docker system prune --volumes`。

## 22. 正式上线闸门

- [ ] 正式发布标签、服务器提交号和镜像版本一致。
- [ ] `.env.production`、四个 secrets 和数据库备份均已加密异机保存。
- [ ] SQLite 正式迁移报告无数量差异，抽查至少 20 起案件。
- [ ] 221 项后端测试、78 项前端测试和构建在发布提交上通过。
- [ ] Python 与前端依赖审计无已知高危漏洞。
- [ ] PostgreSQL、Redis、后端、Celery、前端全部健康。
- [ ] 只有 80/443 对业务网络开放，数据库、Redis、后端不直接暴露。
- [ ] HTTPS、证书链、续期演练和客户端信任正常。
- [ ] 管理员、分析员、只读账号和越权测试通过。
- [ ] 案件、研判、图谱、时空、报告、模型和 WebSocket 业务验收通过。
- [ ] PostgreSQL 备份恢复演练成功并形成记录。
- [ ] 磁盘、容器健康、证书到期和备份失败已纳入单位监控。

全部通过后再从测试域名切换到正式业务域名。鉴于案件和模型配置均为受控数据，不建议在
没有 VPN、访问控制、HTTPS、审计和备份的情况下直接向公网开放。
