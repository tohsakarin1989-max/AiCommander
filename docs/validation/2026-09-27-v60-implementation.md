# v6.0 主链归一实施与验证记录

日期：2026-09-27。范围：本次用户授权“推进到6.0版本”，不执行 v6.1—v6.5，不提交或发布 GitHub，不操作目标服务器或真实业务库。

源码版本：`6.0.0-stable`。验证只覆盖下列明确列出的范围，未宣称全部仓库测试或正式业务验收通过。

## 基线与保留项

- 开始时 VERSION / README 为 `5.4.0-stable`，发布提交 `56e63e4`；另有前几轮未提交业务精简/语义修复。
- AGENTS、历史计划、演示数据脚本、设计参考与既有文档等原有改动保留，不整仓覆盖或打包提交。
- 原始案件、事件、生产设施、人工确认、会议和历史报告不删除；地图数据、路由引擎、检索模型不下载或重建。

## 本轮工作包

| 包 | 实现 | 边界 |
| --- | --- | --- |
| A 案件工作界面 | 以 workspace 读取标准画像、处理卡、自动摘要、图示与成果；去掉重复 GET 分析 | 缺失/过期画像显示等待；GET 不生成卡或运行模型 |
| B 当前组合成果 | 原基础成果 → 冻结道路附件 → 不可变组合；主体/范围/车型/路网和版本绑定 | 旧 schema 双读；无有效道路不以空间候选充道路结果 |
| C 来源与人工决定 | 线索入来源哈希与 Outbox；链条后台续算、过期标记；经验状态认具体版本 | 人工确认不复制到新内容，未核实线索不成事实 |
| C 旧口径与统计 | 停旧辖区评分/重复生成，条件组不评级；报告事件后台授权聚合 | 保留台账、反馈、历史与独立业务，失败不显示零 |
| D 能力开关 | 日常新查询独立启停；历史、取消和到期清理继续 | 不自动配置、调用或验证模型；运行中心不混淆规则与模型 |

## 升级兼容说明

1. 新链条版本列迁移 `f94a53da8bc4 → v60c01`（文件 `v60c01_chain_source_versions.py`）；旧推断未绑定来源版本时标历史，不伪装当前。
2. 标准画像结构升为 6.0。新录入和相关变更自动排队。升级旧库后管理员使用既有 `/api/admin/case-profiles/backfill` 按 `next_after_id` 分批回填至空；后台 Worker 完成前旧成果显示等待，不要求一线用户操作。
3. 旧 JSON 经验卡保留原位、明确历史来源；不自动猜测合并到新资产，也不继承其确认。已有版本化资产优先按具体版本读取；旧 case-only 确认不能默选新版本。
4. 新组合不改旧附件的父 ID，不重新触发道路队列；相同输入复投幂等。过期/异权限分支不作为当前成果补位。
5. 当前新增开关、编排与队列迁移见 [运行开关说明](../runtime-feature-switches.zh-CN.md)。

## 验证证据

以下均为隔离/合成输入，不以本机测试替代目标服务器或真实业务效果。不同批次存在交集，不把数量相加当作独立全量覆盖。

| 检查 | 本轮结果 | 说明 |
| --- | --- | --- |
| 后端主链集成 | 286 passed，19.86 秒 | 案件、链条、预检/批量复核、workspace、统计、经验版本、组合/导出/授权、查询与清理、旧评分停用、生产配置和健康检查 |
| 前端针对性回归 | 65 passed，13 文件 | 助手开关、旧入口/运行能力、组合成果、工作界面、报告/事件统计及预检/批量复核等 |
| 前端生产构建 | 通过 | TypeScript 与 Vite；保留既有大包体提示，不等于浏览器实测或部署完成 |
| 运行版本声明与治理 | 22 passed，1.23 秒 | 管理员 GET 只读代码声明，不注册历史评测版本；声明不等于实际执行证据 |
| SQLite 升级与独立恢复 | 通过 | 实际 Alembic 升级，旧人工确认保留；禁止就地降级；独立恢复库再升级，原库升级后事实与线索仍保留 |
| PostgreSQL 升级与独立恢复 | 1 passed，3.19 秒 | 本机真实 PostgreSQL 16.15 / PostGIS 3.6.4 / pgvector 0.8.6，专用空库，详见下节 |
| 实际文档组件 | 通过 | 组合成果用本地 Node 文档组件生成 DOCX；图片使用隔离合成输入，不作为离线地图覆盖验收 |
| 组合与查询/设施收尾 | 59 passed | 组合 15、设施档案 14、道路查询 2、查询工具 28；含实际数据库撤权、历史时间窗与当前组合分离回归 |
| 查询相邻流程 | 32 passed | 查询生命周期、API 与工具循环，收尾修复后通过 |
| 最终组合引用补强 | 54 passed | 组合 17、查询道路 6、初始上下文 20、追问 6、设施摘要 5；与其他批次有重叠 |
| 版本/启动/迁移收口 | 16 passed，11.83 秒 | 版本一致性、查询开关、独立进程启动与 SQLite 恢复；源码版本同步后通过 |

主链集成执行：

```bash
cd backend
venv/bin/python -m pytest \
  tests/test_case_service.py tests/test_chain_analysis.py tests/test_suggestions.py tests/test_batch_review.py \
  tests/test_case_change_chain_v60.py tests/test_v60_workspace_adapters.py tests/test_v60_business_statistics.py \
  tests/test_retained_business_chains.py tests/test_legacy_business_workflows.py tests/test_case_profile_daily_review.py \
  tests/test_case_automation.py tests/test_case_workspace.py tests/test_experience_cards.py tests/test_knowledge_asset_lifecycle.py \
  tests/test_case_results.py tests/test_case_result_access.py tests/test_case_result_pipeline.py tests/test_case_result_backfill.py \
  tests/test_case_result_composition.py tests/test_query_capability_v60.py tests/test_intelligent_query_api.py \
  tests/test_intelligent_query_tasks.py tests/test_optional_runtime_schedule.py tests/test_runtime_status.py \
  tests/test_jurisdiction_context.py tests/test_legacy_scoring_retirement.py tests/test_production_config.py \
  tests/test_observability.py tests/test_well_attention.py -q --no-cov
```

此后独立复核发现的查询缓存撤权与时间窗版本混用问题按影响范围补测，不反复运行无关地图下载、路由构建和全项目检查。

### PostgreSQL 实际组件

新增 `tests/test_chain_source_postgres_v60.py` 为显式启用测试，常规环境默认跳过，只有专用临时库参数和确认标记同时匹配才执行。本轮使用本机缓存 `aicommander-postgis-vector:16-0.8.6` 镜像，新建仅监听回环地址、随机端口、tmpfs 数据目录的合成空库。

验证空库到 v5.4，再升级 `v60c01`；合成案件原文、历史人工确认保持。升级后新增事实和线索仍保留；破坏性降级被拒绝。用 `pg_dump` 备份恢复独立 v5.4 库，再升级至 v6.0 成功，没有覆盖当前库。

最初标准 PostGIS 缓存镜像缺少 pgvector，在既有 v5.1 迁移门槛被正确拒绝；改用上述已有兼容镜像后通过，没有绕过门槛、下载或编译。两个本轮专用临时容器已停止自动删除，其合成内存数据已销毁；无挂载卷、无遗留容器，既有业务库和演示容器未触碰。本机迁移成功不等于服务器部署或生产保存性能通过。

### 保存性能

固定发布基线 `56e63e455a97a6685925156be0eaab440702d60b` 与冻结候选源码对比。候选包含已存在未提交修复，不把全部收益归因于本轮改动。

- 本机 macOS arm64、Python 3.13.4、临时文件 SQLite，200 起合成含坐标案件；禁止网络。
- 三轮交错运行，每轮每种操作预热 10 次、测量 50 次；创建和更新各 150 个测量样本。
- 创建 P95：289.55 ms → 8.62 ms；更新 P95：193.16 ms → 8.85 ms。本机业务服务层相对退化不超过 5% 的目标通过。
- 未测 HTTP、并发负载或 PostgreSQL 保存延迟，不宣称目标服务器同速。源码包哈希、全部样本与环境记录见 [JSON 证据](evidence/v60-save-performance.json)，复现入口 `scripts/verify-v60-save-performance.py`。

### 审查重点

- 同一组合通过父基础成果和道路附件再次鉴权，不同主体/范围不共享当前指针；道路条件过期不继续声称当前可用。
- 重复完成通知幂等、组合完成事件不重新发起道路计算；新组合不改变旧附件父 ID。
- 案件、线索和派生事件同事务；人工确认的来源变更只提示，不静默删除或继承确认。
- 模型未配置仍明确未启用；规则完成不计模型成功；关闭新查询保留授权历史和取消，普通队列继续清理过期任务。
- 查询历史的组合引用逐项重新鉴权、核对内容摘要，撤销道路许可后不能继续通过缓存读取、追问或导出。按历史完成时间筛选时固定对应分析运行的成果；只有基础成果则明确部分完成，不替换为当前另一份道路组合。
- 设施档案的当前候选只读同授权主体下的当前组合；旧空间结果保留历史标识，不混入当前候选。

版本同步后再次 `npm run build` 通过，`git diff --check` 通过。仅保留既有前端包体提示，没有绕过失败测试或降低业务权限门槛。浏览器交互、目标服务器、外部模型及真实业务效果不在本轮验收结论内。

最后只读复核确认上述 P1 查询缓存撤权、P2 历史运行与当前组合混用均已封闭，新增用例与代码路径一致；该窄范围复核未发现剩余可复现阻断，不冒充全项目安全审计。

## 未执行事项

- 未调用真实模型；模型能力未验证，不计为已接通。
- 未部署目标服务器、未进行真实业务验收。
- 未提交、推送、创建 Release；本次只推进本地源码与交付材料。
