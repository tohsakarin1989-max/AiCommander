# v8 道路私有情景与反馈字段迁移：组件验收记录

日期：2026-10-08。范围：当前工作区的 v8.3 道路额外排除子图，以及 v8.0 `feedback_known_fields` 增量迁移。本文不代表整个 8.x 已发布、目标服务器验收或正式业务效果。

## 1. 实际结果

| 验证层 | 实际执行 | 结果与边界 |
| --- | --- | --- |
| PBF、源保留、发布与私有子图 | `test_road_scenario_networks_v83.py`、`test_road_publication_service.py`、`test_road_source_filter.py`、`test_road_build_job.py` | 49 通过、7 跳过；其中图编译在普通安全测试中使用明确标注的替身，PBF 解析和过滤使用实际 osmium。跳过项不计入原生能力。 |
| 最终私有子图安全与恢复 | `test_road_scenario_networks_v83.py` | 补齐身份锁和中断恢复后，19 通过、1 原生专用项跳过；下行另行实际执行该原生项。 |
| 真实原生路由 | `test_real_private_graph_route_matrix_and_range_use_exclusion`，`AIC_SCENARIO_NATIVE=1` | 1 通过，无跳过；真正编译两张微型合成路网并调用固定版本 Valhalla 的路径、距离矩阵和可达范围。 |
| 选择器、当前授权与刷新 | `test_road_network_service.py`、`test_road_network_selection.py`、`test_road_refresh_jobs.py` | 本地隔离 SQLite 38 通过。 |
| 真实 PostgreSQL 迁移 | `test_case_feedback_postgres_v80.py` | 一次性 PostgreSQL 内 1 通过，无跳过；从空库升级至 v7.5 基线，再检验 v8.0 升级与回退保护。 |
| 新语义写入后的真实备份恢复 | `test_case_feedback_restore_postgres_v80.py` 的 seed／verify 两阶段，阶段间执行实际 `pg_dump`／`pg_restore` | 2 通过，无跳过；恢复到另一空库，核对 121 张表、4 条合成案件原文、来源标记、反馈语义和序列。详见第 6 节。 |

这些执行有重叠，不将次数简单相加为独立能力或业务样本数。第一行的 XML 保留了追加恢复测试之前的完整回归；第二行覆盖随后新增的恢复行为。

### 真实道路结果

同一合成起终点、同一授权、同一参考车型：

- 基准图路径：232 米，使用道路 10。
- 私有图额外排除道路 10 后：676 米，改走道路 20，未使用道路 10。
- 同一私有图距离矩阵：677 米，与路径计算差 1 米。
- 可达范围返回同一私有图版本；默认选择器仍选择基准图。
- 私有图校验值：`75d6ec33a3f0efbd8ac6630ef6ba781bfdfadbf6e92fd8729737662715896d6b`。

这是合成小路网的真实引擎验证，不是两市全域性能、真实道路完备性或现场通行验收。未重新下载公共地图、未重新构建路由依赖，也未声称已有历史图均保留了源包。

## 2. 安全与恢复实现

相关文件：

- `backend/app/services/road_retained_source.py`
- `backend/app/services/road_scenario_networks.py`
- `backend/app/services/road_publication_service.py`
- `backend/app/services/road_network_service.py`
- `backend/app/services/road_source_filter.py`
- `backend/app/services/road_graph_builder.py`

### 只做删减，不扩大权限

1. 正常发布保存已经过授权过滤的 `eligible.osm.pbf`，位置为服务器配置目录下 `.sources/<SHA-256>/`；源包、来源描述和摘要共同校验，禁止链接替换。
2. 情景只接受服务器目录中已登记道路标识，再使用原冻结治理计划解析对应道路。HTTP 不接收源文件路径、任意道路编号或编译参数。
3. 子图从既有授权图的源包额外删除道路，复用既有转向限制重写逻辑；不修改真实道路、门禁或正式案件事实。
4. 私有图不会发布为默认图。目录行保留非公开状态，并由私有 builder 标识隔离；即使误删除私有标记，也不能直接作为正常图解析。
5. 只有内部工作任务的用户／情景／图版本上下文可以使用私有图；每次读取重新检查原图授权、数据范围、车辆、条件、源版本及校验值。撤权、原图变化、用户变化或情景不匹配均拒绝。

### 中断和故障

- 源解析、关系处理和分块哈希检查取消；原生编译取消后终止并回收自身子进程。
- 整个私有准备过程预算为 180 秒，单次原生编译上限 120 秒。队列在准备完成后保存检查点并让出执行，下一次租约再做矩阵计算。
- 身份级服务器文件锁防止同一私有子图并行构建。进程退出自动释放锁；下一持锁任务可重试遗留 `building_private`，复用同一目录身份。
- 构建失败记为 `failed_private`，相同输入可重试；失败、取消和工作目录异常均不替换基准图。
- 旧图未保留源包返回 `road_scenario_source_not_retained`；文件缺失返回 `road_scenario_source_unavailable`。不使用软避让或直线距离代替严格排除。
- 路网缺失等部分结果后的显式续试由情景任务层维护；本组件的幂等复用不自动重新触发业务任务。

服务器应继续保留 `.sources`，不能在清理构建工作目录时一起删除。源包本身不等于可向联网侧发送的公共地图；其位置及权限遵循内网配置。磁盘不足、完整厂区构建耗时、目标服务器 Worker 重启演练仍需在相应环境单独记录。

## 3. PostgreSQL 升级与受保护回退

使用已有镜像 `aicommander-postgis-vector:16-0.8.6` 启动一次性数据库，固定数据库名 `aicommander_v80_isolated_migration`：无公网、无宿主端口，数据目录为 512 MiB 临时内存挂载。测试容器只加入这个隔离网络命名空间。

实际过程：

1. 空库运行完整迁移到 `v75r01`。
2. 插入合成旧记录，包含报案 `false`、立案 `true` 和两项 `null`。
3. 升级 `v80f01` 并重复升级一次。
4. 断言原始文本和反馈原值不变、新来源标记仍为空、案件修订数量没有增加。
5. 在尚无新增来源语义时，降级 `v75r01` 再升级成功。
6. 插入带明确来源标记的新记录。
7. 再次降级被 `feedback_provenance_requires_compatible_backup_before_downgrade` 拒绝；三条记录、当前版本和新标记完整保留。

此验收证明迁移在真实 PostgreSQL 上执行，不能替代业务数据库备份恢复、应用版本兼容或现场数据验收。已有新来源标记时，不能直接删列回退；须使用兼容备份并保护升级后新增原始业务数据。

一次性数据库容器已停止并自动删除，合成数据库不可恢复；不存在真实数据。XML 已保留，迁移可用同一测试重新生成。测试默认跳过，仅显式设置 `AIC_V80_POSTGRES_MIGRATION_URL`，且数据库名符合上述隔离名称时运行。

## 4. 环境和重现约束

- 原生道路：已有 `aicommander-v52-native-workflow:local`，Linux Python 3.12，固定 `pyvalhalla` 版本由编译入口校验，实际 osmium 解析；容器 `--network none`，源码只读挂载、临时输出可写。
- PostgreSQL 应用侧：已有 `aicommander-v70-runtime:validation`，使用当前工作区 `app` 与 Alembic 目录的只读挂载。
- 两个镜像没有单独安装 pytest；只把宿主现有测试库目录追加到 Python 搜索路径，优先使用镜像内原生依赖，关闭 pytest 插件自动加载。没有下载或安装新依赖。
- 容器测试出现 `Unknown config option: asyncio_mode` 警告，原因是禁用插件自动加载；本包为同步测试，该警告不表示异步路径已通过。
- 首次尝试的旧道路镜像缺少 osmium，全部跳过；较旧镜像执行迁移又缺少 pgvector。这两次环境探测不计为通过证据，随后已改用现有依赖齐备镜像完成上述实际验收。
- 原生小夹具仅用于正确性，不代表真实业务数据；未使用当前聊天模型充当系统模型验收。

本地选择器回归命令：

```bash
cd backend
venv/bin/python -m pytest tests/test_road_network_service.py tests/test_road_network_selection.py tests/test_road_refresh_jobs.py -q
```

在上述隔离原生环境、当前只读源码下：

```bash
python -m pytest tests/test_road_scenario_networks_v83.py tests/test_road_publication_service.py tests/test_road_source_filter.py tests/test_road_build_job.py -q
AIC_SCENARIO_NATIVE=1 python -m pytest tests/test_road_scenario_networks_v83.py::test_real_private_graph_route_matrix_and_range_use_exclusion -q
```

镜像无 pytest 时按上述追加本机已有测试库的方式调用 `pytest.main`；不能把宿主编译扩展替换进 Linux 原生依赖路径。PostgreSQL 专用测试要求新的空隔离库，不应指向任何现有业务库。

## 5. 留存证据

XML 均为合成测试，无业务记录、凭据或精确生产位置。仓库工作区副本：`output/v8/component-evidence/`。原临时副本保留在 `/tmp/aicommander-v83-native-ojl0OR/`。

| 文件 | SHA-256 |
| --- | --- |
| `unit-pbf-final.xml` | `87fa2cd364520ca88ad8272a4bec61f851b886e27557e0a2027fdd208fff7676` |
| `private-recovery.xml` | `a582780ca816a493025cd27a739b6fd0d47955fd490840c3d6e33e57d67bcfba` |
| `native-private-final.xml` | `578a5ec7d520b9fdddcf93768e1111342d4f300aecedbf324a126de792e24ff1` |
| `postgres-migration.xml` | `31be778c78900663d6faf9bb36841a23a11421b058f6fcb53a6ae27b56142188` |

本包未修改版本号、未提交或发布 GitHub。保存性能复测由主任务在无本包并发测试的环境另行执行，本文不代替该门槛。

## 6. 补充：新来源语义写入后的真实备份恢复

本节补足第 3 节只验证迁移和受保护降级、尚未实际 dump／restore 的边界。未修改业务代码或部署工程。

### 可复现入口

```bash
backend/venv/bin/python scripts/verify-v80-postgres-restore.py \
  --output /tmp/一个新建或空的合成验证目录
```

脚本只使用已有的固定验证镜像，`--pull=never`，不会读取部署配置、连接现用服务或接受任意数据库地址。宿主测试库默认取 `backend/venv/lib/python*/site-packages`；有多个目录时必须显式指定 `--test-libraries`。源码及测试目录只读挂载；没有下载、安装或重构依赖。

执行流程：

1. 创建一次性 PostgreSQL 容器，`--network none`、无宿主端口、512 MiB 临时数据目录；源库固定名 `aicommander_v80_restore_source`。
2. 从空库迁移至 `v75r01`，写入两条合成旧记录：保留 `false/true` 历史值和 `null/null` 未知值。
3. 升级至 `v80f01`，再写入两条含新增原文的记录：一条有明确 `police_reported=true`、`case_filed=false` 及来源标记，另一条字段未知、来源标记为空列表。
4. 使用 PostgreSQL 自带 `pg_dump --format=custom` 生成真实备份。
5. 用 `createdb --template=template0` 创建另一个空库 `aicommander_v80_restore_target`。
6. 实际运行 `pg_restore --exit-on-error --single-transaction --no-owner --no-privileges`，不使用 `--clean` 或 `--create`，不覆盖源库。
7. 重新读取恢复库，核对全部 121 张表的列类型／默认值／空值要求、索引、约束、记录数、序列状态，以及四条案件的完整行和反馈语义。恢复库新增记录的主键序列检查成功，探针记录回滚。
8. 再读取源库，确认备份和恢复全过程未修改源库。结束后停止并自动删除本轮容器，保留备份和证据。

### 验证结果

- seed 阶段 **1 通过**，verify 阶段 **1 通过**，均无跳过。
- 旧 `false/true` 仍是 `legacy_unverified`，没有变成用户已明确确认的事实。
- 旧 `null` 和新增未知记录仍是 `unknown`。
- 新来源标记完整恢复，明确 `true/false` 仍分别返回可信的是／否。
- 升级后新增中文原文、完整案件行、迁移版本 `v80f01` 和序列保留。
- 恢复前后的规范化快照 SHA-256 一致：`b9a5683de5a4ff665398f15fda015c11b52f7fa73c5f4e51a176b0ccb3985436`。

首次严格 SQL 字串比较发现 PostgreSQL 16 在重新解析时产生 **19 处等价拼写差异**：常量 varchar 数组向 text 的转换分配，以及纯 AND 条件括号扁平化。这不是丢失索引或约束。测试仅针对三种已观察到的无损拼写进行明确规范化，不删除任意括号、不忽略约束或索引，也不接受其他结构差异。原始前后快照和每项差异均完整保留；列、数据、序列及反馈语义使用原值严格比较。

### 环境与证据

- 实际工具：`pg_dump (PostgreSQL) 16.15 (Debian 16.15-1.pgdg12+2)`。
- 数据库镜像：`aicommander-postgis-vector:16-0.8.6`，ID `sha256:52a58988963cd4d838f4bb62ca111aa9525a63a7563970bca1f657ec1bc2cbfa`。
- 应用验证镜像：`aicommander-v70-runtime:validation`，ID `sha256:f3fb2b371bd492c3f0ea4beb42afe78c56c92ba18adb202cf630335bd65e0630`。
- 自动化脚本：`scripts/verify-v80-postgres-restore.py`。
- 测试：`backend/tests/test_case_feedback_restore_postgres_v80.py`，默认跳过；只允许上述固定隔离库名、localhost 和显式阶段。
- 成功证据：`output/v8/component-evidence/postgres-restore/`；原临时副本 `/tmp/aicommander-v80-restore-vYfLGY/`。
- 首次严格比较未通过的证据仍保留于 `/tmp/aicommander-v80-restore-P7EVZu/` 与 `/tmp/aicommander-v80-restore-eWdEQ3/`，没有覆盖为通过结果。

| 文件 | SHA-256 |
| --- | --- |
| `feedback-v80.dump` | `4710c75f40b50a1afe7a35a3beec4476515f1c59d74bd2d75462a26e4f8b2c13` |
| `seed.xml` | `9161cbcf04b85a62cae165fd32bd75077ff9bf3e0521ac1fc6b327722abeb006` |
| `verify.xml` | `aeb4905bd314e4d49914b94f581bb47bac0427989f4e8a234d8f9dfd4cc97d8d` |
| `restore-report.json` | `69e845718f3104e9d2466f55930954ea14d3c17ebfcdfcec907c441959811387` |

备份约 462 KiB，全部为合成数据，可重新创建。容器临时数据已删除；保留的 custom dump 可恢复。本节证明新数据库语义经真实备份恢复不丢失，不等于目标服务器部署、生产规模耗时、数据库角色／秘密恢复或地图／文件卷联合灾备验收。未重跑无关业务回归、未提交或发布。
