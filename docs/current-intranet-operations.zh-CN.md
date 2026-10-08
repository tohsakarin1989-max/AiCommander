# 当前版内网启用与恢复主手册（v7.0）

本文件是 7.x 运维主入口；具体应用版本以本次批准的 `VERSION`、交付清单和发布说明一致为准。历史部署记录保留在[旧运维手册](server-deployment-runbook.zh-CN.md)，不要照抄其中 v3.x 镜像、迁移头和覆盖恢复命令。

**边界：** 脚本检查通过是源码/交付证据，不等于目标服务器已部署。未验证的模型、道路、资料或恢复能力必须标明。无需等全厂资料齐全、30 天试用或固定样本数才发布源码；向员工开放前仍须验证本次实际开放的功能。

## 1. 最小启用顺序

1. 明确内网地址、HTTPS/单位 CA、服务器架构、资料负责人、管理员和备份位置。业务端只开放 HTTPS，数据库、Redis、后端不直接暴露。
2. 接收批准版本的源码、同架构镜像及交付清单。用单位已准备的 Docker、Compose、curl、Python 3.10+ 标准库核对；脚本不替内网下载或安装这些工具。
3. 复用 `scripts/init-production.sh` 初始化配置与分离密钥。配置文件权限 600、密钥目录 700、密钥文件 400/600；不覆盖既有密钥，不把密钥贴到聊天或工单。
4. 配置实际厂区、账号可见范围、已批准地图、第一份生产台账。使用普通账号检查边界，不以管理员看到全部数据代替权限验证。
5. 员工完成“录一案、遇错续填、找回本案、看一口井、打开并导出现有材料”。未知资料仍可保存；模型故障不阻断这些已启用的核心能力。
6. 留下备份与独立恢复记录、使用指引及报错联系人；未就绪能力保持关闭或明确受限。

首次录入不要求配置高级模型或道路计算。未发布地图须明确提示，不能偷偷请求公网；未安装完整导出运行环境不能宣称 Word/PDF 已可用。

## 2. 选定能力与准确镜像组合

| 能力 | 配置及组合 | 额外交付与验收 |
|---|---|---|
| 核心录入/查询 | `docker-compose.production.yml`；backend、celery、celery-beat 同版，frontend 同版 | 固定摘要 PostgreSQL 16 **同时含 PostGIS/pgvector**、Redis；真实迁移与恢复 |
| 中文 Word/PDF | `ENABLE_DOCUMENT_EXPORT=true` 自动追加 `docker-compose.document-renderer.yml` | backend-documents 同版镜像；LibreOffice、中文字体、Node/docx、Playwright/本地浏览器、地图渲染模块；真实合成文档导出 |
| 道路与导出组合 | `ENABLE_ROAD_ANALYSIS=true` 自动追加 `docker-compose.road-runtime.yml`（不再叠加 documents 覆盖它） | backend-roads 与 road-worker 同版，普通消费者复用组合 API 镜像；Valhalla 及批准路网；不因可见数据自动获得道路许可 |
| 显示现有离线地图 | 已发布地图数据，不需要开启地图构建 Worker | MBTiles/包集、中文字形、样式、图标、地名索引、来源许可和 manifest；断网冷启动 |
| 内网地图构建 | `ENABLE_MAP_BUILD=true` 选择既有 map-build profile | 同版 map-worker；地图构建与发布权限不交给普通员工 |
| 智能查询 | `ENABLE_INTELLIGENT_QUERY=true` 选择共享 agent-lab 队列 Worker | 不会因此开启实验 Lab；可用规则工具与实际模型状态分别展示 |
| 本地语义/模型 | 按[本地检索说明](local-history-embedding.zh-CN.md)单独准备并验证 | 模型包、许可、清单、依赖和真实内网测试；不能把规则查询称真实模型验收 |

本次一键脚本自动组合核心、documents、roads、map-build、query。语义 overlay 尚需按其专用手册核定组合，不要盲目放在 roads 后覆盖成不含道路的镜像；未核定组合不作为一键交付能力。

联网区只制作公开依赖/运行镜像，不带案情、重点井精确位置或生产台账。内网运行使用 `DEPLOY_IMAGE_MODE=prebuilt`。原有默认 `build` 仅适用于受控构建区，会构建并拉取基础层，不能拿它证明离线部署。

### 无需重编路由引擎的应用更新

若已有同架构、通过验证的道路＋报告组合运行镜像且依赖相容，先 `docker image inspect 本地镜像标签 --format '{{.Id}} {{.Os}}/{{.Architecture}}'` 与批准清单比对。在隔离构建目录使用已核对的本地标签（或确实可解析的仓库摘要引用）：

```sh
docker build --pull=false --network none -f deploy/road-api/Dockerfile.cached \
  --build-arg ROAD_API_RUNTIME_IMAGE=aicommander-backend-roads:已核对的本地运行基底标签 \
  -t aicommander-backend-roads:本次候选版本 .
```

裸 `sha256:<image ID>` 可用于 `docker image inspect/run`，不要直接传给 Dockerfile 的 FROM；BuildKit 可能将它解释为名为 sha256 的远程仓库。构建前后均核对本地基底标签未变。

只复制应用与迁移，使用 `pip --no-index --no-deps` 检查依赖，并校验唯一迁移头及必须存在的历史契约；不将迁移头写死为某次旧发布。基础镜像缺依赖即停止，回受控构建区准备，不临时在内网联网修补。`--network none` 只限制构建步骤网络，不能替代构建器的外网隔离；真正目标部署只导入已验收镜像，不现场构建。

不开道路但要导出时，可用同一个已验收组合镜像 ID 标记同版 `backend-documents`；普通 backend/Worker 仍须来自同版应用，不能留在旧版本。新装场景在构建区用 `backend/Dockerfile --target document-renderer` 制作报告镜像；默认 `runtime` 不含完整导出依赖。

在受控构建区使用 `DEPLOY_IMAGE_MODE=build` 且只开启 documents 时，叠加配置分别构建 API 的 `document-renderer` 与 Celery 的 `runtime`；后者只构建一次，由 Beat 和已启用的 Agent Worker 共用轻量 core 镜像。道路组合不叠加 documents，仍共用组合运行镜像。实际 Compose 解析已核对这两个构建目标和同版镜像对应；这不是一次干净环境完整镜像构建成功的证明。内网 `prebuilt` 不执行上述构建，须预先交付 API 报告镜像和普通 Worker 同版 core 镜像，再按批准清单核对。

## 3. 离线交付清单与预检

从 [交付模板](../deploy/offline-delivery.example.json)复制到受控交付目录。模板中的占位 ID、0 字节、空摘要故意不能通过验收；不得将模板当正式证据。

- 顶层：`schema_version=1`、`purpose=delivery`、应用版本、`linux/amd64` 或 `linux/arm64`、本次开放能力。
- 文件：明确相对路径、用途、来源版本、字节数、SHA-256；拒绝越界和符号链接。
- 镜像：每个启用服务的准确引用、不可变 image ID、架构、组件版本。仅列本次开启的可选 Worker；核心 Worker 不可缺。
- 核心文件用途：`release_archive`、`image_archive`、`operations_guide`。
- 地图用途：`map_packages`、`map_manifest`、`map_fonts`、`map_style`、`map_icons`、`place_index`；可以指向同一经专用验包的归档，但必须分别说明相应资源版本。总包哈希不证明内部地图质量。
- 道路再登记 `road_source`、`road_manifest`；语义再登记 `embedding_bundle`、`embedding_manifest`。未交付资源应去掉相应能力，不能填一个“已完成”字符串。

制包人在已知文件和镜像准备好后，可只读采集摘要，输出待批准清单：

```sh
umask 077
python3 scripts/verify-offline-delivery.py /secure-transfer/delivery-input.json \
  --root /secure-transfer/aicommander-release --version 本次批准版本 \
  --check-images --record > /secure-transfer/delivery-candidate.json
```

`--record` 仅记录已声明文件/镜像，不补缺项、不批准来源，也不证明能力可用。签发人核对版本、来源和清单，通过单位受控路径同时传递可信的清单摘要。不要在目标机重新计算一份摘要后自动信任它。

目标机先校验批准清单与镜像归档再执行 `docker load -i /secure-transfer/aicommander-release/images.tar`，不运行 `docker pull`。文件校验与运行依赖核对分两步：

```sh
python3 scripts/verify-offline-delivery.py /secure-transfer/delivery-approved.json \
  --root /secure-transfer/aicommander-release --version 本次批准版本 --purpose delivery
python3 scripts/verify-offline-delivery.py /secure-transfer/delivery-approved.json \
  --root /secure-transfer/aicommander-release --version 本次批准版本 --purpose delivery \
  --platform linux/amd64 --check-images --probe-runtime
```

第二步只创建无网络、只读、无业务卷的临时依赖探针；不访问业务库。架构参数必须换成目标机实际架构。文件及依赖通过不替代地图断网打开、实际 Word/PDF、道路限制和迁移验收。

在 `.env.production` 设置：

```dotenv
APP_VERSION=本次批准版本
ALEMBIC_TARGET=head
DEPLOY_IMAGE_MODE=prebuilt
POSTGIS_IMAGE=sha256:已验收且同时包含两扩展的镜像ID
OFFLINE_DELIVERY_MANIFEST=/secure-transfer/delivery-approved.json
OFFLINE_DELIVERY_ROOT=/secure-transfer/aicommander-release
ENABLE_DOCUMENT_EXPORT=true
ENABLE_ROAD_ANALYSIS=false
ENABLE_MAP_BUILD=false
ENABLE_LEGACY_OPERATIONS_MODULES=false
```

再执行 `sh scripts/preflight-production.sh`。7.x 及以后不跳过扩展检查；7+ prebuilt 还核对交付文件、目标架构、Compose 实际镜像与声明能力。密钥只读取到本机进程做配置验证，不输出。

通过且取得本次部署授权后执行 `sh scripts/deploy-production.sh`。prebuilt 后续每次 `run/up` 均禁止拉取，`up` 禁止构建；缺镜像、缺资源、能力不符在迁移和业务服务改变前停止。部署自动产生的 pg_dump **仍只是数据库升级前备份，不是完整灾难恢复包**。

## 4. 完整恢复对象清单

| 对象 | 当前真实存储 | 恢复要求 |
|---|---|---|
| 案件、修订、来源、已上传证据原件、材料与权限 | PostgreSQL；`evidence_objects.content` 为二进制原件 | 同一检查点 custom dump、版本清单及校验；恢复后核对原件内容 SHA-256，不只数表 |
| 只有引用/元数据、尚未上传的外部原件 | 不保证已在系统 | 资料负责人登记外部原件是否另行保管；缺失标未备份，不能凭 storage_key 声称已有内容 |
| 地图、字形、地名索引、样式、路网与文件包 | `map_packages` 卷，对应 `/var/lib/aicommander/maps` | 整个对应目录及文件清单；与数据库快照/包版本一起恢复 |
| 生产台账原始文件 | 按实际导入/原件保存情况核对 | 数据库中的标准行不等于完整 Excel 原件；系统外保管者另列受控原件归档 |
| 应用、Worker、导出运行库、前端 | 本版已验收镜像 | 不可变 ID、架构、代码包及批准交付清单；留上一相容版 |
| 非密钥部署配置、反向代理、单位 CA 配置 | `.env.production`、实际 Nginx 配置等 | 加密备份；登记非默认路径和能力组合，不输出环境全文 |
| 会话/配置加密主密钥、数据库/Redis 密码、证书私钥 | secrets 与单位证书保管设施 | 与数据备份分离加密保管，登记可取回回执；丢失 secret_key 不能靠新生成密钥解开旧配置 |
| Redis 与后台进度 | Redis AOF 及数据库 Outbox/持久任务 | 明确哪些可重投、哪些须恢复；恢复前冻结消费者，不能无差别重放批准或正式写入 |

当前 Compose 没有独立“附件文件卷”；不要创建一个空目录冒充已备份原件。可重建的缓存、临时地图构建目录不等同事实源，但是否重建应逐项登记。不得把精确生产地图和案件包回传联网制包区。

## 5. 捕获一个一致的恢复点

须经批准的维护窗口：先阻止新的业务写入，再停止**所有**应用/后台写入者（含已启用的 agent、road、map Worker 与 Beat）；数据库保留运行。待活动事务退出后，使用同一配置组合保存数据库、地图及外部原件。记录检查点、停写起止时刻、应用/迁移/地图版本；运行中的两个独立备份不能自行声称同一时点。

沿用 `scripts/backup-production.sh` 取得 custom dump、`.manifest` 和 `.sha256`。对地图卷先只读核对具体挂载来源，再用已导入工具镜像、`--pull=never --network none`、**只读挂载已核实的精确卷**归档；不得为“备份”创建空的新卷。受控归档不能含链接、绝对路径或 `..`，核对工具会拒绝这些可危险解包的内容。

把 [恢复清单模板](../deploy/recovery-inventory.example.json)填为 `purpose=recovery`，登记：

- `database_dump`、`database_manifest`、加密的 `configuration_archive`、`originals_inventory`；地图启用还须 `map_files`、`map_inventory`。
- 原件登记 JSON：`database_storage="evidence_objects.content"`；`external_status` 只可为已核对的 `none_recorded` 或 `included`。若为 included，必须提供 `original_files` 文件项。未核对或未备份不能假填 none_recorded。
- `capture.writers_paused=true` 与检查点必须对应实际维护记录，不是点勾即可完成一致备份。
- `secret_escrow` 仅登记分离保管回执号、可取回核验时间；此包不能放密钥。`configuration_encrypted` 仅登记单位批准加密程序的结果，本工具不会鉴定密文安全性。

```sh
python3 scripts/verify-offline-delivery.py /secure-recovery/recovery-approved.json \
  --root /secure-recovery/checkpoint --version 备份对应的相容应用版本 --purpose recovery
```

这一步不调用 Docker、不解包、不执行恢复，只证明已登记的恢复对象齐全且字节一致；不证明来源登记真实完整，也不代表恢复成功。备份、清单、验证证据应复制到受控异机存储；不自动删除旧备份。

## 6. 在独立目标恢复，验证后再决定切换

1. 先保护当前数据库、地图、原件和人工判断，特别是升级后新增数据。回旧版应恢复相容备份到**新库、新卷/新目录**；不能让旧代码直连新版库，不能使用 `pg_restore --clean --create` 覆盖现用库。
2. 独立 Compose 项目明确指定新项目名、配置文件、新 DB 名、不同回环端口和全新的卷。不可沿用现用项目名；任何启动前检查合并配置，禁止 `down -v`、`volume prune` 或自动清空目录。
3. 现有 `verify-backup-restore.sh` 可核对指定 dump 并在**明确指定的隔离项目 PostgreSQL**中创建临时库：

```sh
COMPOSE_PROJECT_NAME=aic_v70_restore_check \
ENV_FILE=/secure-recovery/isolated.env \
BACKUP_FILE=/secure-recovery/checkpoint/approved.dump \
sh scripts/verify-backup-restore.sh
```

该脚本会创建并移除自身临时库，验证迁移版本和非空表；不是完整应用恢复。执行前必须确认 isolated.env、项目名和数据库服务确实独立，不能拿示例命令直指现用服务。

4. 应用联验另建明确名称的空数据库，用对应数据库镜像的 `createdb` 与 `pg_restore --exit-on-error --no-owner --no-privileges -d 新库`，不使用 `--clean/--create`。在独立目录解包已校验的地图：

```sh
restore_maps_dir="$(mktemp -d /srv/aic-restore-check/maps.XXXXXX)"
tar --no-same-owner -xf /secure-recovery/checkpoint/maps.tar -C "$restore_maps_dir"
```

父目录 `/srv/aic-restore-check` 必须已由管理员创建并受控；只能向本次新建空目录解包。将其在隔离 Compose 中绑定到 `/var/lib/aicommander/maps`，核对 UID 10001 所需的权限，不修改原地图目录。

5. 从独立保管处取回原加密密钥，通过秘密文件传递，不能出现在命令参数、shell 历史、清单或截图中。恢复实际反向代理/配置时先核对新地址与端口，不将旧外部地址或宽权限顺带启用。
6. 先不启动消费者，核对数据库版本、原件摘要、地图清单和已发布版本；再按本次能力启用独立消费者，验证录入、附件读取、普通权限、断网地图、中文 Word/PDF。队列补偿按持久任务规则执行，不自动重做正式批准动作。
7. 留下“恢复到哪一相容版本、实际恢复对象、检查结果、缺项、未验证能力”的记录。仅在单独批准切换后修改服务入口；原库/卷保留，升级后新增数据须有独立保全和后续迁回方案。

## 7. 故障处理与真实性

- `ready` 正常不代表地图、导出或模型就绪；分别检查 `/health/maps`、`/health/case-pipeline`、`/health/agents` 和实际文档导出。
- 地图缺失保留空态；模型未接通使用规则；队列积压不阻断正式保存。不要通过开启旧执行模块“恢复流程”。
- 管理员记录队列积压、磁盘、备份时间、版本与能力状态。报错仅附脱敏错误类型和请求编号，不默认收集案情、坐标、密钥或完整提示词。
- 源码/脚本、隔离真实组件、目标服务器、员工实际收益分别记录。探针只证明依赖可用；已有 v4.x/v6.x 验证记录是复用依据，不自动证明当前新镜像或现场已经验收。
