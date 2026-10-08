# v7.0 内网交付与恢复对象工作包验证

范围：部署预检、prebuilt 调用、选定能力组合、只读交付/恢复清单、当前运维主入口。本记录不是全版 Stable、目标服务器部署或现场恢复通过声明。

## 实际改动

- 数据库扩展预检从 `5.*|6.*` 白名单改为数字主版本 `>=5`，7.x/未来主版本不得退回只检查 PostGIS 镜像名字。
- prebuilt 的每次 `run/up` 显式禁止拉取，up 禁止构建；启用的服务名单明确，不要求未开启的道路/地图构建 Worker 镜像。
- `ENABLE_DOCUMENT_EXPORT` 复用现有导出 overlay；道路组合保留优先级；`ENABLE_MAP_BUILD` 复用已有 profile。不改变 Compose 默认版本及业务开关权限。
- 7+ prebuilt 在业务变更前核对批准清单、文件摘要、目标架构、实际 Compose 镜像、不可变镜像 ID 和选定能力。依赖探针只使用临时无网络只读容器，不挂业务卷。
- 两个 road-api Dockerfile 不再将唯一迁移头固定为旧 `b508c42fd75b`，仍要求必须存在的历史契约迁移。不重建路由引擎。
- 恢复清单分别核对数据库、原件登记、地图、加密配置及分离密钥保管回执；有外部原件却无备份、缺地图、修订不符或归档越界均拒绝。工具不备份、不解包、不覆盖、不执行恢复。
- 新运维主手册明确 `evidence_objects.content` 原件在数据库，未上传原件和外部 Excel 原件须另行核对；不存在的附件卷不能假称已备份。

## 执行记录

```sh
cd backend
venv/bin/python -m pytest tests/test_offline_delivery_v70.py \
  tests/test_production_compose.py tests/test_postgres_image_preflight.py \
  tests/test_deployment_rehearsal.py tests/test_production_config.py \
  tests/test_observability.py -q
```

当时 **83 项通过，10.01 秒**。之后新增 3 项实际 Compose 配置解析检查；只针对新增文件复跑 **32 项通过，4.86 秒**。两批覆盖合计 86 个不同用例，不重复累计；其后仅补显式 Python 版本检查和无选定运行依赖时不声称做过探针，再次复跑为 **32 项通过，4.41 秒**。

```sh
sh -n scripts/preflight-production.sh scripts/deploy-production.sh scripts/production-compose.sh
python3 -m py_compile scripts/verify-offline-delivery.py
git diff --check -- scripts/preflight-production.sh scripts/deploy-production.sh \
  scripts/production-compose.sh deploy/road-api docs/server-deployment-runbook.zh-CN.md
```

以上语法与差异检查退出码均为 0。

首次直接调用 `venv/bin/pytest` 时因该入口没有找到 `app` 而退出 4，未执行测试；改用项目解释器 `venv/bin/python -m pytest` 后通过。没有把最初失败隐藏为成功。

## 证据分层

- 文件校验、越界/符号链接、模板不冒充正式清单、恢复缺项、地图 tar 越界：隔离临时文件实际测试。
- Compose 核心/报告/道路＋地图构建三种合并配置：本机真实 Compose 解析，无需 Docker daemon；验证服务名单和镜像组合。
- 预检、缺镜像、探针网络/挂载参数与当前配置一致性：隔离 Docker 命令记录器测试，不冒充实际容器启动。
- 本子任务只读访问 Docker socket 曾被沙箱拒绝；没有启动、停止或更改现用环境。真正 PostgreSQL 迁移、原件联合恢复、镜像应用层构建及中文导出由主任务单独记录，不在此借用结果声称已执行。
- 已修正构建说明：裸 image ID 用于 inspect/run 核对，不直接作 Dockerfile FROM；使用核对后的本地标签或可解析的仓库摘要。`--network none` 不保证 BuildKit 元数据查询绝对断网。

## 运维注意

7+ prebuilt 新增 `OFFLINE_DELIVERY_MANIFEST` 与 `OFFLINE_DELIVERY_ROOT`，须指向已批准的本次交付清单和文件根目录；核对器需要 Python 3.10+ 标准库，脚本不安装依赖。`--record` 只是计算已声明对象摘要，不能在目标机重新计算后自动信任。

核对结果固定包含 `restore_exercised=false`、`target_deployment_verified=false`。配置加密、密钥回执和停写检查点为待运维证据支持的声明；文件校验不能证明单位已经落实这些措施。

`backup-production.sh` 沿用原数据库备份行为，**没有被升级为全系统在线一致性备份**。完整恢复仍须批准维护窗口捕获数据库、文件、原件和配置；在独立目标恢复，保护升级后新增的业务数据，验证后另行批准切换。

后续补证：经主任务授权及工具权限申请，已实际完成专用 PostgreSQL＋合成地图文件＋数据库内原件联合恢复，见[独立真实组件记录](2026-09-30-v70-joint-restore.md)。这没有改变上述库存核对器的真实性边界，也未覆盖现场配置/密钥恢复。

## 发布前环境变量一致性补正

收口审阅发现：预检进程会从指定配置读取 `APP_VERSION` 和 `POSTGIS_IMAGE`，但父部署进程可能仍带着终端导出的旧值；Compose 的终端变量优先于 `--env-file`，从而出现“检查新版、部署旧版”。现由共用 Compose 入口在每次调用前明确从同一个 `ENV_FILE` 读取并导出这两个值，覆盖范围仅限版本和数据库镜像；合法 `IMAGE_PREFIX` 等其他配置保持原约定。

新增/扩展回归包括：核心、文档、道路与地图三种组合在旧 export 冲突时的**实际 Compose 配置解析**；真实 `deploy-production.sh` 全流程命令记录器确认预检后镜像检查、迁移、数据库备份、所有 `run/up` 均使用配置文件值。记录器未启动服务，也不作为容器部署证据。

```sh
cd backend
venv/bin/python -m pytest tests/test_offline_delivery_v70.py \
  tests/test_production_compose.py tests/test_production_config.py tests/test_observability.py -q
```

**71 项通过，9.67 秒**；`sh -n` 与相关差异检查退出码为 0。这里只报告该次定向集合，不与之前重复执行次数相加。

另修复受控构建区 `build + documents` 的新装漏项：documents overlay 仅为 Celery 增加 `runtime` 构建定义，确保 API 改成报告镜像后仍构建普通消费者共享的 core 镜像；Beat 不重复构建，roads 组合不受影响。补充两构建目标、镜像和道路互斥断言后，仅复跑 `tests/test_offline_delivery_v70.py -k real_compose_parser -q`，**6 项通过、30 项未选，1.95 秒**。默认报告镜像版本已同步 7.0。此处只完成真实 Compose 解析与命令行为验证，未执行完整镜像重建；prebuilt 仍须交付并核对所有已选镜像。

能力开关亦统一：`ENABLE_ROAD_ANALYSIS`、`ENABLE_AGENT_LAB`、`ENABLE_INTELLIGENT_QUERY` 从指定配置显式导出，防止 profile 与 API/Worker 或前端构建参数各用一套值。省略字段保持原默认，其中智能查询仍为空值/可空语义，不强制改为关闭。新增一个实际 Compose 回归，覆盖明确关闭、查询单开、Lab 单开及全部省略四组与终端冲突的输入；`-k 'real_compose or deployment_uses_same'` **8 项通过、29 项未选，5.32 秒**。无容器启动、镜像构建或业务库访问。
