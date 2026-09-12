# 2026-09-12 v2.1–v3.6 留存后端业务链核验

核验对象是当前 `4.5.0-stable` 工作区保留的历史业务能力。按 v2.1–v3.6 release、知识资产、工作台、证据图谱、态势、Agent runbook 和 v3.1–v3.6 实施记录确定范围。本记录不覆盖另行核验的会议、旧巡逻和案件 CRUD，不代表目标服务器已经投产。

## 执行结果

- 留存模块 25 文件：**280 passed，0 skipped，18.43 秒**。
- 新的跨模块链和 A 阶段依赖：**31 passed，0 skipped，4.89 秒**。随后补强跨区地图与 Agent 成功链，新增文件最终 **3 passed，2.80 秒**，不重复累计。
- 离线地图、空间分析、出包、注册和安装：**87 passed，0 skipped，2.29 秒**。
- 上述不同文件合计 **398 项通过**；这是分组执行结果，不是另一次完整后端全套结果。
- `scripts/tests` 最新全量：**155 passed，5.33 秒**。仅有已有 Pydantic 类配置弃用提醒。
- 四个历史验收脚本的全新 SQLite 迁移和必需表阶段均通过；脚本语法与 `git diff --check` 通过。
- 使用真实公共离线地图包执行 `verify-v36-competition-demo.sh`，**5/5 轮通过**。

所有业务测试使用合成数据及隔离 SQLite；新链使用真实登录、`AuthMiddleware` 和生产 `get_db` 厂区绑定，没有注入假 principal 或用依赖覆盖绕过范围约束。外部模型关闭；需要故障或模型返回时，仅替换本地模型传输对象。没有真实消息、生产数据库或线上配置修改。

## 逐功能与完整链

| 留存能力 | 核验的完整路径和边界 | 当前证据 |
| --- | --- | --- |
| v2.1 Agent 执行与审计 | 显式选数 → 规则工具 → 事件/工件 → completed；模型异常保留规则工件并 degraded；重复投递幂等、源版本改变禁止旧任务重放、取消/超时停止后续写入 | `test_agent_lab_runtime.py` 30 项；`test_agent_lab_config.py` 14 项；新跨模块链第 3 项真实登录验证关闭 404、队列故障 503、规则执行成功、关闭后重放 404 |
| v2.2 地图数据管家 | 名单/范围/写开关 → 候选 → 人工审批 → 幂等应用；暂停、禁用和名单撤销阻止写入；已核验资产不被修改 | `test_map_steward_pilot.py` 12 项，以及 Agent runtime 审批回归 |
| v2.3 案件数据管家 | 名单/显式选案 → 质量与缺口 → 只读工件；禁止案件候选写入，暂停取消活动任务，重放重新检查名单/来源 | `test_case_steward_pilot.py` 6 项 |
| v2.4 双域辅助 | 有界案件+资产范围 → 空间条件与依据 → 工件/指标；不生成正式结论或审批写入，停用可取消两类任务 | `test_dual_domain_pilot.py` 6 项；Agent runtime 双域工具检查 |
| v2.5 运行中心与评测 | 运行 → 时长/调用/错误/估算成本 → 角色受限概览；凭据不在返回体；评测不足明确报缺口 | `test_agent_observability.py` 7 项、`test_agent_lab_eval.py` 2 项 |
| v2.6 知识/经验资产 | 案件事实与证据 → 经验草稿版本 → 人工确认 → 相似经验推荐 → 采纳记录 → 主动选择引用 → 报告快照 → 人工确认 | `test_knowledge_asset_lifecycle.py` 13 项；新跨模块链第 1 项走真实登录并确认案件事实不变。覆盖重复生成、草稿/归档禁用、源案件/证据/地图变化拒绝旧稿确认 |
| v2.8 工作台 | 有且仅一个下一步 → 生成经验 → 复核 → 报告 → 复核完成；会话恢复/切换/完成幂等、去除 URL 参数、禁止外部路径；viewer 不记录会话/指标 | `test_workbench.py` 9 项；新链验证知识资产状态变化立即推进工作台，并隐藏未授权厂区案件 |
| v2.9 证据与串案图谱 | 已有案件/材料/知识引用 → 来源、事实、推断、缺口 → 人工复核队列；同样源数据版本稳定、无事实写入，敏感材料路径和精确井坐标不回传 | `test_evidence_graph.py` 7 项；新链连接确认报告引用与证据节点，验证跨区单案 404、串案结果排除未授权案件 |
| v3.0 态势 | 等长相邻时间窗 → 数量变化/热点/井点条件 → 最多三项参考；空数据不编造建议，范围和数据版本可追溯 | `test_situation_analysis.py` 12 项；新链验证真实 analyst 仅统计授权 2 案，不包含另一厂区案件 |
| v3.1 地图治理 | 来源 → 字段/坐标模板 → 预览零写 → 导入 → 异常坐标/越界行隔离 → 冲突人工 retry → 修正源文件、新 revision 重导 → 资产版本 | `test_map_foundation.py` 14 项；新链第 2 项验证重放同批次 200、越界隔离、修正重导、版本留痕、分析员可看授权资产但不能进管理接口。旧空间分析回归另 32 项 |
| v3.2 离线地图 | ZIP/摘要/逐瓦片验证 → 注册/安装 → 构建快照 → 发布 → 瓦片读取 → 回滚；错误包不替换 current，旧图/内部生产要素保留 | `test_offline_maps.py` 23 项、`test_public_map_bundle_builder.py` 18 项、注册/安装各 7 项；持久化上传/worker/API/自动发布共 38 项；真实 62,097 瓦片 ZIP 五轮演练 |
| v3.3 案件后台预处理 | 保存先成功 → 事务 outbox → worker 画像 → 版本与缺口 → 分析；不依赖模型或 Redis 完成保存，幂等、回补游标、超时租约与旧 worker 令牌被拒绝 | `test_case_pipeline.py` 24 项；`test_case_ai_foundation.py` 8 项、`test_batch_review.py` 10 项、`test_suggestions.py` 6 项、`test_automation_alerts.py` 4 项；五轮真实包演练覆盖保存后自动推进 |
| v3.4–v3.5 双域候选与部署参考 | 当前地图快照+案件画像 → ≤3 个候选 → 支持/反证/缺口 → 日/周态势与≤3建议 → 人工反馈；不自动建执行任务 | `test_deployment_advisor.py` 5 项、`test_competition_rehearsal_v36.py` 2 项；五轮证据中每轮候选 3、依据覆盖 100%、正式数据无变化 |
| v3.6 治理与故障恢复 | 厂区读写约束、版本化评测/明确真值、故障恢复、过期令牌拒绝、重复投递 → 可复核结果 | `test_governance_v36.py` 15 项；实际五轮彩排见下 |
| 保留智能查询 | 创建/读取/取消 → worker 租约 → 受限只读工具 → 从工具结果生成卡片；模型不能指定任意 SQL/shell 或编造答案，缺模型/坏返回/超时/撤权明确失败或降级 | API 8、worker 4、tools 28、tasks 12、loop 12 项，共 64 项。本轮未调用外部模型 |

## 修复的历史验收脚本误报

`verify-knowledge-assets.sh`、`verify-workbench.sh`、`verify-evidence-graph.sh`、`verify-situation.sh` 原本在 `alembic upgrade head` 后仍断言旧 revision `a7d9e1f2b304`。本工作区唯一 head 是 `b508c42fd75b`；因此正确的全新库反而触发 `AssertionError`。

修复后共同调用 `scripts/verify-sqlite-schema.py`，只读打开既有数据库，读取当前仓库 Alembic heads，要求数据库版本集合完全相同，并保留各模块原有必需表检查。不会把缺库创建成空库，也不会接受空、旧或未知 revision。新增 `scripts/tests/test_sqlite_schema_verification.py` 6 项回归。

已在全新临时库真正执行完整 `alembic upgrade head`，再执行四个脚本的相同 schema 检查阶段。没有重复四次前端构建；前端由并行主核验提供最终构建证据。

## 真实公共地图五轮彩排

执行：

```sh
MAP_BUNDLE_FILE=/Users/tohsakarin/work/AiCommander/backups/map-foundation/daqing-qiqihar/20260907/daqing-qiqihar-public-basemap-20260907-z6-14-rectangular.zip \
EVIDENCE_FILE=/tmp/aic-audit-v36-retained-five-rounds.json \
sh scripts/verify-v36-competition-demo.sh
```

包 SHA-256：`7887b6cd656b908cdacb799831c435dd97f6967f6c9c69670c7b5416da6d696e`；z6–14 共 62,097 瓦片。一次性数据库运行后已删除。

| 轮次 | 故障场景 | 结果 |
| --- | --- | --- |
| 1 | 正常规则链 | profile completed、3 候选 |
| 2 | 本地对象注入模型超时 | deterministic fallback、degraded 留痕、规则链完成 |
| 3 | outbox worker 暂停再恢复 | 保存先成功、独立 worker 会话恢复完成 |
| 4 | worker 认领后重启 | 过期租约恢复、旧令牌提交被拒绝 |
| 5 | 幂等重放 | 无重复正式数据或执行任务 |

五轮均：依据覆盖 100%，正式案件及领域事实未改变，没有创建执行任务。演练保存了运行时 1,006 个源码文件指纹且期间源码稳定；其它并行修复后不能把该指纹误称为最终整个工作区指纹。

先尝试的历史 `*-complete.zip` 含矩形范围外瓦片，当前深度验包以 `tile_coverage_mismatch` 拒绝。随后使用已有的 `*-rectangular.zip` 通过。没有修剪历史包或放松验收断言；不能将旧 `complete` 包直接用于当前导入。

## 日志与边界

- `/tmp/aic-audit-retained-v2-v3-tests.log`：280 项。
- `/tmp/aic-audit-retained-chains.log`：31 项；`/tmp/aic-audit-retained-chains-final.log`：补强后新 3 项。
- `/tmp/aic-audit-retained-offline-maps.log`：87 项。
- `/tmp/aic-audit-scripts-final.log`：155 项。
- `/tmp/aic-audit-legacy-head-before.log`：旧断言失败证据；`/tmp/aic-audit-legacy-head-after.log`：新 helper 6 项。
- `/tmp/aic-audit-legacy-migrations.log`：全新库迁移及四模块表/head 检查。
- `/tmp/aic-audit-v36-retained-five-rounds.json` / `.log`：真实包五轮证据。
- `/tmp/aic-audit-v36-stale-complete-package.log`：历史不合规包被拒绝。

尚需真实业务验收：经验资产 runbook 的 10 起历史案、5 起目标案和人工适用性签认；工作台不少于 20 次真实会话的节时与采纳情况；地图真实来源字段、控制点转换精度及现场坐标校准；经授权的真实模型供应商连通与业务输出质量。本轮合成模型/故障注入不能证明这些外部环节已正常。

## 附：并行会议修复的独立复核

按主核验分工，仅对并行代理的会议安全目录、模型空密钥和会议失败状态修改进行只读复核，复现测试存于 `/tmp`，产品修复由原责任代理实施。

- 真实登录和生产 `get_db`：匿名目录 401；分析员/只读用户的目录仅 `id/name/role/is_active`；模型管理 403；未授权会议 404；跨区、撤去写权限的创建请求不入队；合法会议保留正确辖区；空 `api_key` 的 HTTP 编辑保留原密文。**1 passed，1.74 秒**，`/tmp/aic-audit-meeting-auth-review.log`。
- 独立发现：最终模型返回合法空 JSON `{}`，聚合排名元数据使原非空检查放行，错误产生 completed 报告。修复为综合报告必须有有效非空摘要。
- 独立发现：报告和 completed 先提交、主持人最终总结后提交；后者失败仍留下报告和 100% 成功通知。修复为报告、最终排名、总结与终态一次事务提交，成功通知在提交后发送。
- 原两项失败复现修复后 **2 passed，1.16 秒**，`/tmp/aic-audit-meeting-independent-review-after.log`；修复前日志 `/tmp/aic-audit-meeting-independent-review.log`。本次复核未发现安全目录、密钥保留或辖区约束的新问题。
- 全量测试随后发现历史项目门禁也写死旧迁移号。已将 `test_deployment_rehearsal.py` 相应检查更新为四个脚本的 helper 调用和各自确切必需表集合，保留拒绝旧 head 的要求。该文件 12 项加严格 helper 6 项 **18 passed，3.61 秒**，`/tmp/aic-audit-legacy-gates-final.log`。
