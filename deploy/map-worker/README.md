# v4.0 候选：隔离地图 Worker

此组件尚在部署验收，不是 v4.0 Stable 发布声明。它处理内网已上传的公共地图包，
不承担联网采集。关闭 Worker 不影响已发布地图和案件录入；上传任务留在数据库等待领取。

## 构建与运行

在联网构建机从仓库根目录构建：

```sh
docker build -f deploy/map-worker/Dockerfile -t aicommander-map-worker:v4-candidate .
```

基础镜像使用固定 digest。Node 与样式校验依赖只进入独立地图镜像；核心后端镜像不变。
Python 依赖复用后端及隔离地图构建清单，前端依赖通过锁文件安装且禁止安装脚本。
Dockerfile 专用忽略文件采用白名单，不向构建上下文发送备份、密钥、业务数据库或本地环境文件。

生产配置校验、备份和迁移沿用现有部署脚本。完成本版本全部门禁后，显式启用：

```sh
COMPOSE_PROFILES=map-build sh ./scripts/deploy-production.sh
```

如同时启用 Agent Lab，现有部署脚本仍处理 `agent-lab`；地图服务不依赖 Agent 开关。
管理员确认自动更新范围后，可设置 `MAP_AUTO_PUBLISH_AREA_IDS=1,2`（默认空关闭）。
自动更新仍检查上传管理员当前厂区权限，失败保留旧图。详见 [自动发布闭环](../../docs/validation/v4.0-map-auto-publication.md)。
后续升级应保持该环境变量，或在统一部署入口中显式传递 `--profile map-build`。
离线目标机先导入经校验的同架构镜像，不能执行需要联网拉取的构建步骤。

只停止地图后台处理（不删卷，不改当前地图）：

```sh
docker compose --env-file .env.production -f docker-compose.production.yml \
  --profile map-build stop map-worker
```

## 隔离与容量

- 只消费 `map_build` 队列；并发 1、预取 1，每个子进程完成一项任务后退出。
- 仅连接 Docker 内部 `data` 网络，无宿主机端口；不接入对外的 `edge` 网络。
- 只读根文件系统、非 root UID/GID 10001、移除 capabilities、禁止提升权限。
- 容器限制 2 CPU、4 GiB 内存、128 个进程；Node 老生代限制不替代容器内存限制。
- 共享 `map_packages` 供后端读取已安装地图；独立 `map_build_scratch` 存放重组与校验临时文件。
- 临时空间需要容纳整包及校验副本，不使用核心后端的小容量内存临时盘。主机磁盘限额和孤立临时目录保留策略仍需单独验收。
- 正常异常路径会清理本次临时目录；强制终止可能留下孤立目录，不能将其当成成功成果，也不能在任务运行时手工清理。

## 当前证据与剩余门禁

Compose 语法解析、部署隔离测试及既有生产配置/健康测试通过（27 项）。

2026-09-10 实际镜像构建及断网容器验证已完成：

- Linux ARM64 镜像 config：`sha256:2922b4b71a344d56e25d5f3e0c5568c94fb2666720656ea0af280ace06235f8b`。
- 首次运行发现本机部分源码私有权限导致 UID10001 无法读取；镜像内只给代码树增加读取/目录遍历权限，未改变宿主源码权限。
- 修复后构建自检在 UID10001 下执行，Node 24.21.0 与官方样式校验器可用。
- 运行参数实际读回：UID/GID10001、network=none、只读根目录、4GiB 内存和128进程限制。
- `verify-runtime.py` 使用显式测试开关、内存 SQLite 及卷内独占临时目录，拒绝 production 环境。
- 真实两市包270资产、1128893张瓦片通过“分片导入→数据库入队→处理→持久安装”，耗时29.33秒。
- 首次权限失败保留为缺陷证据，不计通过；修复后完整复测退出0。

2026-09-10 真实 Redis/Celery 验证通过（独立 internal 网络、无端口、一次性卷）：

- `verify-queue.py` 限定测试库 URL、地图目录、UID10001 和显式开关，只上传/读取，不直接执行 Worker。
- Redis 未启动时成功持久排队，导入 ID `24d79271-a4a4-4995-bce7-12b7f40f1d3a`；Worker/Beat 保持重连。
- Redis 恢复后，现有30秒 Beat 调度自动投递，Celery 任务 `fa6e6b9b-dfe6-40fa-9c19-c8a6440525bc` 于11:31:09 UTC领取。
- 处理中11:31:36 UTC重启无持久化测试 Redis，任务11:31:37完成，耗时28.62秒。
- 数据库最终为 `render_validated`、安装为 `installed_integrity_verified`，1128893张瓦片；Worker11:31:38自动重连。
- 下一次真实调度返回 `None`，同一导入未重复处理。
- 首次测试辅助容器缺少开发密钥，配置校验退出且未创建任务；补齐一次性开发配置后重新执行，未使用生产凭据。

本场景使用持久 SQLite，不代表 PostgreSQL 并发/事务、强杀 Worker 租约回收、生产 Compose 整体联调已通过。
此容器验收的 `publish_ready=false`；新增的显示登记和隔离库发布链路已另行验证，
见 [显示登记验证](../../docs/validation/v4.0-map-display-registration.md)。
它不代表道路能力或业务系统 current 已发布，浏览器真实后端验收仍待完成。
