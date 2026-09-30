# v6.5 后端全量扫描与定向收口记录

日期：2026-09-30。范围为当前工作区 R10—R12 整合后的后端回归，不代表目标服务器部署、真实模型或正式业务验收。

## 结论与证据口径

- 实际执行过一次完整 `pytest tests`：**2,601 通过、47 失败、55 跳过，295.38 秒**，退出码为 1。该首次失败记录保留，不改写为全量通过。
- 对失败逐项定位、修复实现或更新已变更的有效测试契约，随后执行受影响的 22 个测试文件：**197 通过、3 跳过、1 失败，70.79 秒**。其中 R12 续跑文件 21 项、R10 材料文件 18 项通过。
- 最后一项失败为隔离演练期间其他任务修改源码，触发 `candidate_source_changed_during_rehearsal`。暂停全部源码编辑后，只重跑这一项：**1 通过，4.84 秒，退出码 0**。保留源码前后指纹门禁，未将其禁用或放宽。
- 首次全量中另一个本地 HTTP 场景因沙箱禁止监听失败；经授权允许本机回环监听后，原单项 **1 通过，1.91 秒**。它只验证真实 HTTP 协议链路，不接真实模型。
- 因此，本次全量发现的失败均有后续针对性通过证据；**没有第二次完整全量通过记录**，也不把多批重叠用例相加成新的测试总数。

全量原始日志和 JUnit XML、定向合集以及单项复跑保存在本机临时目录 `/private/tmp/aic-v65-backend-regression.VPR5pD/`。这些日志是本地过程证据，不作为业务资料或凭据上传。报告可随源码保存，临时日志不承诺长期保留。

## 隔离方式与实际命令

全量默认连接设置为新建临时目录内的 SQLite 文件；各测试继续使用自己的内存/临时 SQLite fixture。关闭向量外部依赖、Agent Lab 和外部模型，不读取项目现用数据库，不访问生产路由或业务模型。

全量命令在 `backend` 目录运行，除一次性测试 `SECRET_KEY` 外，环境及入口如下：

```bash
umask 077
validation_dir=$(mktemp -d /private/tmp/aic-v65-backend-regression.XXXXXX)
export DATABASE_URL="sqlite:///$validation_dir/default.db"
export AUTO_CREATE_TABLES=false ENVIRONMENT=test
export AUTH_REQUIRED=false SESSION_COOKIE_SECURE=false
export ENABLE_VECTOR_DB=false ENABLE_AGENT_LAB=false
export AGENT_MODE=off AGENT_USE_EXTERNAL_MODEL=false
export ENABLE_LEGACY_OPERATIONS_MODULES=false
venv/bin/python -m pytest tests -q -ra --junitxml="$validation_dir/results.xml"
```

实际输出另重定向到同目录 `pytest.log`，保存原始退出码。测试中自行启用认证的 fixture 仍验证真实权限，不因全局默认 `AUTH_REQUIRED=false` 跳过权限断言。

完成修复后的定向合集使用上述关闭外部依赖的环境，默认数据库改为 `sqlite://`，实际执行：

```bash
venv/bin/python -m pytest \
  tests/test_case_pipeline.py tests/test_case_history_index.py \
  tests/test_case_search_page.py tests/test_case_sources_v61.py \
  tests/test_case_result_backfill.py tests/test_dashboard_activity.py \
  tests/test_experience_cards.py tests/test_legacy_history_report_migration.py \
  tests/test_competition_rehearsal_v36.py tests/test_case_result_pipeline.py \
  tests/test_case_road_status.py tests/test_fresh_database_v61.py \
  tests/test_history_migration_v63.py tests/test_frozen_insight_inputs.py \
  tests/test_model_data_egress.py tests/test_v60_business_statistics.py \
  tests/test_retained_business_chains.py tests/test_topic_continuation_v64.py \
  tests/test_result_materials_v65.py tests/test_legacy_meeting_workflow.py \
  tests/test_case_ai_foundation.py tests/test_ai_structured_output.py \
  -q -ra --tb=short \
  --junitxml=/private/tmp/aic-v65-backend-regression.VPR5pD/final-targeted.xml
```

这批结果为 197 通过、3 跳过、1 个源码指纹变化失败。最终安静窗口单项：

```bash
venv/bin/python -m pytest \
  tests/test_competition_rehearsal_v36.py::test_competition_rehearsal_cli_executes_real_bundle_and_writes_evidence \
  -q --tb=short \
  --junitxml=/private/tmp/aic-v65-backend-regression.VPR5pD/cli-final.xml
```

结果 1 通过。指纹覆盖前端、后端、测试、版本文件等源码，排除 `docs` 等记录目录；暂停的不只是 `backend/app`。

本机 HTTP 单项：

```bash
venv/bin/python -m pytest \
  tests/test_case_local_semantic_model.py::test_real_loopback_http_contract_without_model_acceptance_claim \
  -q --tb=short
```

结果 1 通过。只使用隔离合成请求与本机监听服务，不发送案件原文到外部模型。

## 发现及修复

### 实现问题

1. **会议报告权限过滤晚于分页。** `app/api/reports.py` 原先先截取数据库页，再剔除来源不可见报告；同一辖区内含受限来源的报告会占用页位置。现在稳定排序后流式检查来源权限，再应用可见集合的 `skip/limit`。没有扩大可见范围或减少总体统计。回归包含 105 份可见报告、同辖区受限来源报告、首末分页与跨页无重叠，保留总量及去重口径断言。
2. **隔离演练错误移除 UTC 时区。** `app/release_checks/competition_v36.py` 在 SQLite 分支将带时区合成时间改成 naive 值，而现有案件入口把 naive 值按本地时间解释，导致闭合窗口跨期。移除该转换，让案件服务统一规范化；保留本期/上期计数和连续五轮断言。

### 旧测试契约与 fixture 适配

- Outbox 现在同时承载案件画像、专题来源变动和后台统计。案件队列用例按 `case.analysis.requested`、回填用例按自身事件类型断言精确数量、状态和幂等；页面只读用例比较读取前后全部事件总数，而不是假定建案后整个 Outbox 必为零。没有放宽“页面读取不得写入”的要求。
- 经验与报告必须使用已存在冻结成果。fixture 先验证缺成果时返回 409，再实际执行案件后台画像/成果链路，随后验证按需生成、确认、归档和引用。没有在测试中恢复同步原文分析。
- 历史统一检索显式构建版本化索引，保留较早案件、621 条授权覆盖、否定文本、当前权限及部分降级断言。草稿/归档经验仍可按原状态读取，但不冒充已确认经验进入检索。
- SQLite 新建及增量迁移的当前头更新为 `v65r01`，保留拒绝重复初始化、原文保全、独立恢复和非破坏回退检查。
- 冻结候选重放遵循现有规则：只有地图中的储存点而没有案件依据，不生成囤储候选；保留来源版本、篡改拒绝和无实时查询断言。
- 向量脱敏用例创建真实分片索引所需的本地合成嵌入，不再只填已退出读取路径的父向量字段；继续严格验证权限及不返回完整原文。
- 道路状态的资料缺失响应增加结构化依赖项，仍区分失败、未知和已完成，GET 不创建计算。
- 原有人员/车辆、回收、证据、独立事件、真实告警、经验人工生命周期及只读图谱等保留业务链通过 4 项专门回归，没有以删除旧测试代替兼容。

首次全量加载到的 R12 证据撤回 fixture 使用了非法枚举值；负责代理改为模型允许的 `revoked`，最终 21 项续跑用例覆盖撤销、案件源版本失效和证据撤回三种情形。R10/R12 并发修复分别记录在它们的验证文档，本报告不抢改其代码。

中间定向批次也保留失败：第一批 87 通过/3 失败，第二批 40 通过/1 失败/3 跳过；它们用于定位剩余经验契约和真实分页问题，不与最终结果累加。

## 55 项跳过的原因

| 类别 | 数量 | 未在默认全量开启的条件 |
| --- | ---: | --- |
| PostgreSQL / PostGIS | 13 | 专用可丢弃实例及显式确认参数 |
| 浏览器与地图渲染 | 9 | 本地真实浏览器、固定地图资源及显式开关 |
| Office PDF | 1 | 离线 Office 引擎显式验收 |
| Redis Worker 故障演练 | 2 | 独占可丢弃 Redis 演练开关 |
| 原始 PBF、地图/路网构建依赖 | 18 | `osmium`、离线 PBF 或本地原生构建器；包括 6 个导入阶段跳过 |
| 真实冻结路网与原生路由引擎 | 12 | 固定图、引擎和相应车辆/几何组件 |
| **合计** | **55** | 跳过不等于通过，也不自动等于组件失败 |

最终定向合集的 3 项跳过均为 `test_history_migration_v63.py` 中未显式提供专用 PostgreSQL 的保护。

本轮 R10/R12 已单独执行的真实 PostgreSQL、Chromium 与备份恢复证据见 [R10 材料记录](2026-09-30-v65-materials.md) 和 [R12 专题记录](2026-09-30-v64-topics.md)。单独通过不能把默认全量里的跳过改成通过；未重跑的旧路由/地图构建使用既有版本证据，不重新下载地图或编译路网。

## 前期 R11 与旧入口退出验证

以下是本轮此前已回传的独立批次，不与上方全量或彼此相加。

| 范围 | 当时结果 | 边界 |
| --- | --- | --- |
| R11 助手完整定向集合 | 152 通过、1 跳过，15.08 秒 | 确定性预设、真实合成业务工具、证据/版本、当前权限、预算与取消；跳过为显式 PostgreSQL 项 |
| R11 业务与 Agent Lab 共享协议 | 52 通过、1 跳过，4.07 秒 | 共享声明/信封/预算，不改变 Agent Lab 原有授权 |
| 画像统计与业务工具 | 33 通过、1 跳过，7.58 秒 | 统计工具和续算边界，不充当真实模型验证 |
| 真实 PostgreSQL 截止/取消 | 1 通过，1.20 秒 | 实际 SQL 中止、回滚和连接继续可用 |
| 旧入口退出相关后端 12 文件 | 164 通过，20.99 秒 | 正式路由退出、原历史数据保留、生产配置及观测、独有业务保留 |
| 设置页与旧入口前端 | 9 通过，1.37 秒 | 只读组件/类型范围，不代表浏览器实机流程 |

R11 对应可复跑入口如下；这是当前文件集的复跑选择器，不将其冒充已经遗失的每一批完整原始 Shell 命令：

```bash
venv/bin/python -m pytest tests/test_intelligent_query_*.py tests/test_query_*.py \
  --ignore=tests/test_query_scope_postgres.py -q
venv/bin/python -m pytest tests/test_query_business_v64.py tests/test_agent_lab_runtime.py -q
venv/bin/python -m pytest tests/test_profile_aggregate.py tests/test_query_profiles.py tests/test_query_business_v64.py -q
```

真实 PostgreSQL 使用父任务建立的无持久卷容器 `aic-v65-validation-20260930`，仅访问本轮专用合成库 `aic_v64_query`。以环境设置一次性 `AIC_R11_PG_URL` 和 `AIC_DISPOSABLE_R11=1` 后实际执行：

```bash
venv/bin/python -m pytest \
  tests/test_query_business_v64.py::test_postgresql_deadline_and_explicit_cancel_use_real_statement -q
```

用真实 `pg_sleep` 验证截止和显式取消，随后回滚并查询常量验证连接恢复；无业务数据、模型或外部路由调用。凭据不写入文档。

旧运行路径退出的是人员调度、巡逻执行、旧重点部位及群组正式路由、设置页旧管理入口和无消费者客户端实现；**没有删除历史数据库表或历史记录**。案件人员/车辆、回收、证据、地图设施、独立事件与真实告警保留。`AgentService` 仍被井位关注能力调用，不强行删除活跃服务。相关路由缺席及保留链路现已由本次全量再次扫描；前期 12 文件的完整原命令未在当前过程摘要保留，不伪造该清单。

## 收口边界

- 本报告记录源码及本地隔离组件结果，不宣布 GitHub 发布成功。版本、推送及发布状态由总记录另列。
- 未接真实内网模型；模拟响应、确定性预设及聊天模型不能算作正式模型驱动能力验收。
- 未读取真实业务库，未进行目标服务器部署、真实案例采纳率或地图全域实地确认。
- 保存 P95 首轮明显退化，不能以测试负载为理由直接豁免。材料代理另行定位并修正事务内修订读取开销，完成 50 项相关回归；本报告完成测试后让出负载，正式性能复测由其独立记录，不以这里的通过数替代性能门槛。
- 所有新旧批次都保留实际执行边界；后续远端 CI 或新的完整运行若执行，应追加新的结果，不覆盖本次首次失败记录。
