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
- OpenAI Agents SDK 可选叙述层。确定性内网工具先形成事实与证据，外部模型只接收脱敏特征；默认不调用外部模型、不启用 SDK 追踪。
- 独立 `/health/agents`、JSON 事件轮询、SSE 快照、取消和管理员重放。

当前没有完成、必须在目标环境执行的事项：服务器安装、真实业务人员试用、备份恢复演练、
脱敏业务评测集制作、故障注入和连续五次竞赛演示。完成代码回归不等同于这些现场门槛已经通过。

每次准备部署前可先运行代码级一键验收：

```bash
./scripts/verify-agent-lab.sh
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

## 3. 首次稳定测试部署：保持 Agent 关闭

`.env.production` 保持以下值：

```text
ENABLE_AGENT_LAB=false
AGENT_MODE=off
AGENT_MUTATIONS_ENABLED=false
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

默认 `AGENT_USE_EXTERNAL_MODEL=false`。在完成安全评审前保持关闭。若开启，必须同时保持：

```text
AGENT_EXTERNAL_DATA_POLICY=redacted_only
AGENT_PROVIDER=openai_agents
AGENT_SDK_TRACING_ENABLED=false
```

内网确定性工具先计算事实、距离、风险因素和证据关联。外发层删除姓名、电话、证件号、车牌、
完整案情、地址、案件编号、井名、精确经纬度和内部路径，只保留临时化名、区间和统计特征。
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
| `v2.0.1-test` | Agent 默认关闭、独立健康检查、增量迁移 | 干净服务器部署、备份恢复、全量核心回归 |
| `v2.0.2-stable` | 核心流程不依赖 Agent | 指定用户试用、耗时和故障基线 |
| `v2.1-agent-lab` | 队列、状态、轨迹、成果、审批、隐藏入口 | 中断恢复和接口性能对照 |
| `v2.1.1-shadow` | 三类只读工具、规则降级、零正式写入 | 脱敏真实样本影子结果 |
| `v2.1-demo` | 候选、管理员审批、幂等和源版本校验 | 隔离环境全链路录像/记录 |
| `v2.1-competition` | 业务评测 Harness 和故障边界 | 五次演示、人工评分和安全说明 |
| `v2.1.2-hardening` | 权限、脱敏、超时、重试回归 | 并发、断网、Redis/Worker 故障注入 |
| `v2.2-pilot` | 地图候选白名单和一键关闭 | 指定用户试用、零越权写入签字 |
