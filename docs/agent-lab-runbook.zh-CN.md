# “油盾·双域研判智能体”部署、运行与验收手册

> 适用范围：AiCommander Agent Lab。Agent Lab 是核心案件与地图系统的可选辅助层，
> 不参与 `/health/ready` 判定；默认关闭，不得作为案件保存、地图加载和指挥大屏的同步依赖。

## 1. 已实现边界

当前代码已提供以下可运行能力：

- 独立 Agent 运行记录、追加式事件、成果物和审批表；不改变案件、地图资源和报告表含义。
- 案件数据质检、地图数据质检、案件—井位时空融合、综合证据报告四类任务。
- 独立 Celery 队列 `agent_lab` 和单并发 `agent-worker`，最多 8 个工具步骤，默认 120 秒超时，普通失败最多重试 2 次。
- `off`、`shadow`、`assist` 三种模式；前后端双开关隐藏入口。
- 只读分析、工具白名单、脱敏外发、管理员审批、24 小时审批过期、重复提交幂等、源数据版本复核。
- 内网规则引擎是默认主执行层，不需要任何模型密钥，也不会向外部发送数据。OpenAI Agents SDK 仅作为可选叙述适配器；确定性内网工具先形成事实与证据，外部模型只接收脱敏特征，默认不调用外部模型、不启用 SDK 追踪。
- 独立 `/health/agents`、JSON 事件轮询、SSE 快照、取消和管理员重放。

当前没有完成、必须在目标环境执行的事项：服务器安装、真实业务人员试用、备份恢复演练、
脱敏业务评测集制作、故障注入和连续五次竞赛演示。完成代码回归不等同于这些现场门槛已经通过。

每次准备部署前可先运行代码级一键验收：

```bash
sh ./scripts/verify-agent-lab.sh
```

## 2. 三种模式

| 模式 | 前端入口 | 后台运行 | 候选审批 | 正式数据写入 |
|---|---:|---:|---:|---:|
| `off` | 无 | 无 | 无 | 无 |
| `shadow` | 指定角色可见 | 有 | 可形成候选，但不等待审批 | 禁止 |
| `assist` + 写入关闭 | 指定角色可见 | 有 | 管理员可审批 | 审批后仍不写入 |
| `assist` + 写入开启 | 指定角色可见 | 有 | 管理员可审批 | 仅白名单候选可写入 |

写入开启必须同时满足：

```text
ENABLE_AGENT_LAB=true
AGENT_MODE=assist
AGENT_MUTATIONS_ENABLED=true
```

任一条件不满足都按失败关闭处理。首期写入白名单仅包括“未核验地图资源”的名称首尾空格清理，
以及使 Point 几何与现有经纬度一致；不允许修改经纬度，不允许修改已核验资源，不允许 Agent 修改案件。
案件数据管家在任何模式下都保持只读，不生成案件字段候选写入。

### 2.1 v2.2 地图数据管家受控试用

全局 `assist` 开关只是第一层保护。v2.2 还要求管理员在系统内开启地图数据管家、指定试用人员；
指定人员每次必须从真实有效地图资源中明确选择范围，单次默认不超过 100 项。v2.2 时其他 Agent 能力在
`assist` 模式下保持关闭；案件数据、研判结论、经纬度和已核验地图资源均不能由 Agent 修改。

试用状态保存在系统配置表，默认值为“未开启、候选写入暂停、试用名单为空”。接口包括：

| 方法 | 地址 | 权限与作用 |
|---|---|---|
| `GET` | `/api/agent-map-steward/status` | 管理员和分析员查看当前状态与试用指标；只有管理员能看到可选人员名单 |
| `PUT` | `/api/agent-map-steward/control` | 管理员指定试用人员，并开启受控辅助或暂停候选写入 |
| `POST` | `/api/agent-map-steward/suspend` | 管理员一键停用试用、取消活动地图任务、使待审批候选失效 |

在隔离试用环境确认核心链路稳定后，才可配置：

```text
ENABLE_AGENT_LAB=true
AGENT_MODE=assist
AGENT_MUTATIONS_ENABLED=true
AGENT_MAP_PILOT_MAX_ASSETS=100
AGENT_PROVIDER=deterministic
AGENT_USE_EXTERNAL_MODEL=false
```

重新部署后，管理员进入 Agent Lab，选择试用人员并点击“开启受控辅助”。试用人员只选择本次需要检查
的井点或其他地图资源，规则引擎形成问题、证据与候选修正；管理员复核原始台账后决定批准或驳回。
页面展示任务数、候选数、人工采纳率和证据覆盖率，供试用验收使用。

发现异常时优先点击“一键停用试用”。该操作无需等待重新构建前端，会立即阻止新任务、取消活动任务并
使待审批候选失效；已经完成的轨迹和审批记录保留，正式案件和地图数据不变。随后再按第 10 节关闭
全局环境开关并停止 Agent Worker。

### 2.2 v2.3 案件数据管家只读试用

v2.3 在 `assist` 模式新增案件数据管家，但不扩大写入白名单。管理员需单独指定案件试用人员；
试用人员必须明确选择案件，单次默认最多 30 起，且不能在同一任务中混入地图资源。规则引擎输出
缺项、时间与坐标一致性提醒、疑似重复和证据索引，不自动修改案件、人员、车辆、坐标或研判结论。

接口包括：

| 方法 | 地址 | 权限与作用 |
|---|---|---|
| `GET` | `/api/agent-case-steward/status` | 管理员和分析员查看只读试用状态与指标；只有管理员能看到可选人员名单 |
| `PUT` | `/api/agent-case-steward/control` | 管理员指定试用人员并开启或关闭案件只读试用 |
| `POST` | `/api/agent-case-steward/suspend` | 管理员一键停用并取消活动案件质检任务；不修改正式案件 |

案件录入页同时增加服务端规则预检。该预检属于核心确定性能力，不依赖 Agent Worker、Redis、模型密钥
或外网；它只在保存前返回评分、缺项和提醒。预检异常时，页面明确提示人工确认后仍可走原案件保存
接口，保证核心录入不依赖 Agent。

隔离试用环境配置示例：

```text
ENABLE_AGENT_LAB=true
AGENT_MODE=assist
AGENT_MUTATIONS_ENABLED=false
AGENT_CASE_PILOT_MAX_CASES=30
AGENT_PROVIDER=deterministic
AGENT_USE_EXTERNAL_MODEL=false
```

案件只读试用不要求开启 `AGENT_MUTATIONS_ENABLED`。如需同时试用 v2.2 地图候选审批，应另行完成地图
写入安全验收后再开启全局写入保护；该开关不会赋予案件数据管家写入能力。

### 2.3 v2.4 双域融合研判只读试用

v2.4 将“双域融合研判”和“综合证据报告”从影子实验能力开放为指定人员只读试用。管理员需单独
维护双域试用名单；试用人员每次必须同时明确选择案件和状态有效的地图资源，单次默认最多 10 起案件、
100 项资源。系统只在所选范围内计算案件—生产目标距离、时间窗口、历史频次、作案手法标签和历史
聚合热点，不读取范围外案件或资源来补足结论。

接口包括：

| 方法 | 地址 | 权限与作用 |
|---|---|---|
| `GET` | `/api/agent-dual-domain/status` | 管理员和分析员查看只读试用状态与指标；只有管理员能看到可选人员名单 |
| `PUT` | `/api/agent-dual-domain/control` | 管理员指定试用人员并开启或关闭双域只读试用 |
| `POST` | `/api/agent-dual-domain/suspend` | 管理员一键停用并取消活动双域分析和综合报告任务 |

隔离试用环境配置示例：

```text
ENABLE_AGENT_LAB=true
AGENT_MODE=assist
AGENT_MUTATIONS_ENABLED=false
AGENT_DUAL_DOMAIN_PILOT_MAX_CASES=10
AGENT_DUAL_DOMAIN_PILOT_MAX_ASSETS=100
AGENT_PROVIDER=deterministic
AGENT_USE_EXTERNAL_MODEL=false
```

双域研判和综合证据报告不会生成审批项，也不需要开启 `AGENT_MUTATIONS_ENABLED`。其输出必须保留
“历史复盘、待人工复核、不是犯罪预测、相邻不自动构成串并案、不自动派发巡逻”的适用边界。
管理员一键停用后，新任务立即被拒绝，活动任务取消，已有成果和轨迹继续保留。

## 3. 首次稳定测试部署：保持 Agent 关闭

`.env.production` 保持以下值：

```text
ENABLE_AGENT_LAB=false
AGENT_MODE=off
AGENT_MUTATIONS_ENABLED=false
AGENT_PROVIDER=deterministic
AGENT_MODEL=
AGENT_USE_EXTERNAL_MODEL=false
AGENT_SDK_TRACING_ENABLED=false
```

按[服务器部署与运维手册](./server-deployment-runbook.zh-CN.md)完成预检、备份、迁移和启动。
即使 Agent 表已经随 Alembic 创建，`agent-worker` 也不会启动，前端不会显示 Agent Lab。

验收：

```bash
curl -fsS http://127.0.0.1:3000/health/ready
curl -fsS http://127.0.0.1:3000/health/agents
```

第二个接口应返回 `status=off` 和 `affects_core_readiness=false`。随后按既有用例验证案件录入/导入、
保存前预检、批量复核、待办分流、地图、报告、权限和 WebSocket。

## 4. 开启影子运行

只在稳定基线验收后修改：

```text
ENABLE_AGENT_LAB=true
AGENT_MODE=shadow
AGENT_MUTATIONS_ENABLED=false
AGENT_PROVIDER=deterministic
AGENT_MODEL=
AGENT_USE_EXTERNAL_MODEL=false
```

重新构建前端并启动带 `agent-lab` profile 的编排。仓库内 `deploy-production.sh` 会根据
`ENABLE_AGENT_LAB=true` 自动添加该 profile。手工操作等价于：

```bash
docker compose --profile agent-lab --env-file .env.production \
  -f docker-compose.production.yml up -d --build
```

检查 `/health/agents`：Redis 应为 `ok`，Worker 仅在发现主机名以 `agent@` 开头的专用 Worker
时才算 `online`。普通 Celery Worker 在线不能冒充 Agent Worker。

## 5. 用户权限与接口

- 管理员：发起、查看、取消、审批、驳回和重放。
- 分析员：发起、查看和取消；不能审批和重放。
- 只读账号：看不到入口，也不能访问 API。

接口前缀为 `/api/agent-runs`：

| 方法 | 地址 | 说明 |
|---|---|---|
| `POST` | `/api/agent-runs` | 创建任务，返回 202 |
| `GET` | `/api/agent-runs` | 最近运行列表 |
| `GET` | `/api/agent-runs/{run_id}` | 状态、成果、审批和轨迹 |
| `GET` | `/api/agent-runs/{run_id}/events` | JSON 增量事件；支持 `after_sequence` |
| `GET` | `/api/agent-runs/{run_id}/events?stream=true` | 持续 SSE 事件流，终态发送 `stream_end` |
| `POST` | `/api/agent-runs/{run_id}/cancel` | 取消非终态任务 |
| `POST` | `/api/agent-runs/{run_id}/approvals/{approval_id}` | 管理员批准或驳回 |
| `POST` | `/api/agent-runs/{run_id}/replay` | 管理员按当前源数据重放 |

状态主线为 `queued → planning → running → waiting_approval → completed`；
异常终态包括 `failed`、`cancelled`、`expired`、`degraded`。模型不可用但规则成果完整时为 `degraded`。

## 6. 审批和幂等规则

审批执行前逐项校验：运行必须为 `assist`、写入开关必须开启、动作和字段必须在白名单、
目标必须存在且未核验、当前源数据签名必须与分析时一致。审批超过 24 小时自动过期。

同一个审批 ID 重复提交不会重复写入。若人工在分析后修改了源记录，审批返回
`source_changed_since_analysis`，必须重新运行分析，不得强行复用旧候选。

## 7. 数据出域和模型开关

默认配置如下，完整案件质检、地图质检、双域融合和证据报告均可在没有 API 密钥、没有外网的情况下运行：

```text
AGENT_PROVIDER=deterministic
AGENT_MODEL=
AGENT_USE_EXTERNAL_MODEL=false
```

`v2.4.0-stable` 默认生产镜像不安装 OpenAI Agents SDK，也不支持在现场直接打开外部模型开关。
若后续在隔离实验环境选择该 SDK 作为可选叙述层，须先完成数据出域、供应商、密钥保管和
网络策略评审，再基于 `backend/requirements-agent-openai.txt` 构建独立实验镜像，并显式配置：

```text
AGENT_EXTERNAL_DATA_POLICY=redacted_only
AGENT_PROVIDER=openai_agents
AGENT_MODEL=<经评审的模型名称>
OPENAI_API_KEY=<仅保存在受控环境中>
AGENT_SDK_TRACING_ENABLED=false
```

内网确定性工具先计算事实、距离、风险因素和证据关联。外发层删除姓名、电话、证件号、车牌、
完整案情、作案方式原文、线索来源原文、精确案发时间、地址、案件编号、井名、精确经纬度、
地图扩展属性和内部路径，只保留临时化名、分类标签、区间和统计特征。
原始查询文本不会传给外部模型。若开启 SDK 追踪，代码仍强制 `trace_include_sensitive_data=false`；
启用前必须另行完成内网安全评审。

禁止给 Agent 增加任意 SQL、Shell、外部 URL 或未登记网络工具。新增业务工具应先补白名单、
输入输出摘要、证据引用、权限和失败路径测试。

## 8. 本地业务评测 Harness

先制作可丢弃的脱敏 SQLite 副本，在副本上运行 Alembic 到 head，再执行：

```bash
cd backend
venv/bin/python evals/agent_lab/run_local.py \
  --database-url sqlite:////绝对路径/aicommander-agent-eval.db \
  --confirm-isolated-copy
```

Harness 会拒绝默认业务库、内存库、非 SQLite 库、缺表数据库和数量不足的数据集。默认要求
至少 30 个案件和 100 个地图资源，依次运行四种任务，并检查：

- 终态、连续事件序号和完整工具轨迹；
- 有效成果的证据覆盖和适用边界；
- 候选审批未执行；
- 案件和地图资源运行前后摘要完全一致；
- 固定姓名、电话、证件号、井名和精确坐标脱敏；
- 外部模型调用为 0。

报告写入 `backend/evals/agent_lab/results/latest.json`。检查失败退出码为 1；目标不安全、
数据不足或迁移缺失退出码为 2。竞赛冻结应保留五次独立结果，不要反复覆盖唯一一份证据。

## 9. 故障与降级演练

| 故障 | 期望表现 | 核心业务 |
|---|---|---|
| 外部模型超时/非法输出 | 规则成果保留，运行标记 `degraded` | 正常 |
| Redis 中断 | 创建任务返回 503 并记录调度失败 | 正常 |
| Agent Worker 重启 | 任务执行后确认并重新投递；已完成运行重复投递不产生第二份成果；普通失败最多重试 2 次 | 正常 |
| 数据库只读 | Agent 运行失败并留轨迹 | 查询主流程正常 |
| 重复审批 | 返回原审批结果，不重复落库 | 正常 |
| 源数据已变化 | 拒绝旧候选，要求重新分析 | 正常 |

必须分别保存故障前配置、触发步骤、日志时间段、运行 ID、预期和实际结果。

## 10. 紧急关闭与回退

发现异常时先关闭辅助层，不回滚核心数据库：

1. 将 `ENABLE_AGENT_LAB=false`、`AGENT_MODE=off`、`AGENT_MUTATIONS_ENABLED=false`。
2. 停止 `agent-worker`，重新构建前端使入口消失。
3. 验证 `/health/ready` 和核心业务回归。
4. 保留 `agent_runs`、`agent_events`、`agent_artifacts`、`agent_approvals` 作为审计证据。
5. 只有在确认版本整体回滚且备份可恢复时，才按主部署手册回滚应用或数据库。

Agent 表为增量对象，单纯关闭功能无需执行 Alembic downgrade。不要为了关闭 Agent 删除轨迹或审批记录。

## 11. 八周发布门槛映射

| 节点 | 代码/配置支撑 | 仍需现场签字的证据 |
|---|---|---|
| `v2.0.1-test` | Agent 默认关闭、独立健康检查、增量迁移 | 已完成仓库回归与本机隔离部署演练 |
| `v2.0.2-stable` | 首次 stable 发布，保留为不可变历史标签 | 已由 `v2.0.3-stable` 安全补丁替代 |
| `v2.0.3-stable` | 核心流程不依赖 Agent；规范化会话令牌校验；前期测试部署稳定代码基线 | 目标服务器部署、指定用户试用、耗时和故障基线 |
| `v2.1.0-stable` | 内网规则优先的 Agent Runtime、独立队列、状态、轨迹、成果、审批、隐藏入口、三类只读工具、证据报告、幂等、源版本校验、脱敏与评测 Harness | 目标服务器中断恢复和性能对照、脱敏真实样本影子结果、五次连续演示、人工评分和安全说明 |
| `v2.2.0-stable` | 指定人员地图数据管家、真实资源限界、试用指标、管理员审批和一键停用 | 目标服务器指定人员试用、零越权写入签字、真实耗时和采纳率 |
| `v2.3.0-stable` | 服务端保存前预检、指定人员案件数据管家、显式案件范围、只读批量质检和一键停用 | 目标服务器案件样本试用、人工采纳率、零案件自动写入和核心链路降级记录 |
| `v2.4.0-stable` | 指定人员双域研判、显式案件与地图双范围、范围内距离与历史热点、只读证据报告和一键停用 | 目标服务器双域样本复核、范围隔离证据、零正式数据写入、人工有效关联率和连续五次演示 |
