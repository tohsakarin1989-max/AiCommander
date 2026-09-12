# 1.x—3.x 留存功能清单与前端补验

核验日期：2026-09-12。范围是当前工作区对历史能力的继承情况，不是重新证明旧发布说明中的测试成绩。全项目证据另见 [主核验报告](2026-09-12-full-project-verification.md)。本文件不把关闭的模块、不可达的组件或静态页面列作业务通过。

## 取证口径

- 起点为 `git show v1.0.0:README.md` 与 `git show v1.0.0:frontend/src/App.tsx`。README 写了 6 项核心能力；实际标签有 **23 个业务路由**，另有 1 个通配未找到页。因此也核查了 README 未逐条列明的历史事件、图谱、团伙、工作台前身等入口。
- 逐版读取 `docs/releases/v2.0.1-test.md`、`v2.0.2-stable.md`、`v2.0.3-stable.md`、`v2.1.0-stable.md` 至 `v2.6.0-stable.md`、`v2.8.0-stable.md`、`v2.9.0-stable.md`，共 11 份。仓库没有 v2.7 独立发布说明或标签，不补造该版本的功能。
- 读取 [v3.0 发布说明](../releases/v3.0.0-stable.md)、[v3.6 发布说明](../releases/v3.6.0-stable.md) 与 [v3.6 架构](../releases/v3.6-architecture.md)。v3.1—v3.6 六阶段统一冻结于 v3.6，不以不存在的独立 Stable 标签制造验收记录。
- 当前入口以 [App.tsx](../../frontend/src/App.tsx)、[Layout.tsx](../../frontend/src/components/Layout.tsx) 与实际 services 为准：**30 个业务路由（含本次恢复的受控 `/agent-lab`）**。前端测试使用模拟 API，证明呈现和调用边界；浏览器合成数据闭环、后端持久化与权限测试由并行核验另行记录。外部模型真实推理、真实单位台账和目标服务器不在本次通过结论内。

## v1 基线的全部入口映射

“保留”只表示当前有实际组件和服务链；最终业务运行结果须结合下文动作验收和主报告，不能将本列当作全部功能通过。

| v1 路由 / 能力 | 当前页面与主要服务 | 继承状态与本次边界 |
|---|---|---|
| `/` 首页 | Home → 案件统计、最近案件、runtime、研判入口 | 保留；本轮总核验已修最新案件排序、精确案件跳转与奖金开关；页面统计区分全量和本页 |
| `/dashboard` 指挥大屏 | Dashboard → 案件、事件、井点关注、链条地图 | 保留；首轮真实页面及业务核验范围，历史补验不重复修改大屏 |
| `/cases` 案件管理 | Cases → `/cases`，预检、导入、自动画像、批量复核、经验和成果 | 保留并扩展；这是 README 第一项能力；新增事件转案件闭环需实际回读 |
| `/cases/map` 地图 | CasesMap → 案件地图、链条、离线快照 | 保留；生产用受控离线底图，不因旧版支持公网而要求开启公网 |
| `/cases/bonus` 奖金核算 | CaseBonusAccounting → 奖金接口 | **可选、生产关闭**；编译与 runtime 同时允许才挂载；关闭态不计功能通过 |
| `/cases/features` 特征提取 | CaseFeatures → 特征分析接口 | 保留；与 `/case-intelligence` 的标准标签、经验功能并存 |
| `/case-intelligence` 案件研判 | CaseIntelligence → `/case-intelligence/*`、知识资产和报告快照 | 保留并扩展；确定性研判与人工复核是当前主链 |
| `/cases/spacetime` 时空研判 | SpaceTimeAnalysis → 时空统计 | 保留；统计与图表，不自动形成事实关联 |
| `/meetings` 圆桌会议 | Meetings → `/meetings`、模型安全目录、模板、对话、独立分析、排名、报告 | 保留；本次修普通分析员模型目录、历史深链接、异常和只读边界；模型真实联网效果仍未验 |
| `/reports` 分析报告 | Reports → 会议报告、`/reports` 审稿、案件成果目录 | 保留并扩展；已修历史会议定向读取与报告失败态；会议报告与版本化案件成果分开识别 |
| `/conclusions` 结论工厂 | ConclusionFactory → 生成、草稿、会议生成、详情、approve/reject/flag | 保留；本次补只读禁用、列表/详情错误态、复核后详情缓存刷新 |
| `/deployment` 部署建议 | Deployment → `/deployment/*` | 保留为管理员入口；其分析建议不等同于巡逻执行任务 |
| `/area-analysis` 时空区域 | AreaAnalysis → 区域风险、画像及分析 | 保留；来源为历史案件与区域数据，不作为犯罪预测 |
| `/suggestions` 待办中心 | Suggestions → `/suggestions`，跳转预检/复核/经验/事件 | 保留；已修将未办数量冒充完成/复核数量的问题及无作用控件 |
| `/events` 事件中心 | EventCenter → 事件创建、统计、`convert-to-case`，跳转精确案件 | 保留；本次补只读操作边界和失败态；转案件结果需在合成库核实 |
| `/jurisdiction` 辖区底座 | Jurisdiction → 厂区范围、业务资产、离线图层、条件分析、建议反馈 | 保留并扩展；资产维护仅管理员，viewer 不自动调用生成参考的 POST；生产不启用巡逻物化 |
| `/graphs/serial` 关系图谱 | CaseGraph → `POST /graphs/serial`、节点/连线检查、表格、PNG | 保留；本次只读账号明确不能触发 POST 生成，已有依据可从证据图谱读取；非同人同车即串案 |
| `/gangs` 旧团伙分析 | GangAnalysis → 条件组统计/聚类/时段热力/时间线 | **名称与业务语义调整为“相似条件组分析”**；支持时间、空间、手法、现场条件，不宣称真实团伙；修“新建档案”假按钮、参数与结果混用及只读 POST |
| `/patrols` 巡逻执行 | Patrols → 旧巡逻记录/开始/完成/取消/反馈 | **历史兼容模块，生产关闭**；兼容环境另验。图中 4 条硬编码路径现明确“历史路线示意、路线待配置”，不是算法算出的可通行路线 |
| `/assistant` 研判助理 | 当前 Assistant → `/intelligent-queries` | **已被 v4 智能查询替代**；当前支持创建、续问、取消、恢复、Word/PDF，旧自由聊天 UI 不再是本路由；不能把当前查询测试当作旧聊天功能通过 |
| `/agents` 旧 Agent 页面 | 当前 IntelligenceRuntimeCenter → `/admin/intelligence-runtime`、评测 | **已被 v3.6 管理员运行中心替代**；不依赖旧 Agent Lab 开关。本次纠正错误门控；旧 AgentCenter 本次恢复至受控 `/agent-lab` |
| `/settings` 系统配置 | Settings → 模型增改删/默认/连接测试、地图和会议配置 | 管理员保留；人员/重点部位页签仅 legacy runtime 开启才显示/请求，生产关闭不计通过 |
| `/intelli-inspect` 数智巡检 | IntelliInspect → 数据质量与相关业务概览 | 保留入口；以主报告当前 API/页面结果为证据，不据旧名称推导现场巡检执行能力 |

v1 README 的 6 项能力分别落在：案件管理 `/cases`；特征/关联分析 `/cases/features`、`/case-intelligence`、`/graphs/serial`；多 AI 圆桌 `/meetings`；报告 `/reports`；防护建议 `/deployment` 及当前态势/区域页面；模型管理 `/settings`。这六项之外，上表同时保留了标签实际存在的所有入口。

## 2.x—3.x 逐版重大能力矩阵

| 版本来源 | 新增或冻结的重大功能 | 当前承接 / 验证边界 |
|---|---|---|
| [2.0.1-test](../releases/v2.0.1-test.md) | 登录授权、健康检查、迁移备份与试部署；大屏案件/事件/井点；独立 Agent 任务/事件/成果/审批/重放试验 | 身份与运维链保留，首轮已验；Agent 独立旁路见下列兼容状态，试验发布不证明正式生产可用 |
| [2.0.2](../releases/v2.0.2-stable.md) | 案件录入/导入→保存前预检→批量复核→待办→报告；地图/链条/时空；三角色、会话锁定审计；五服务与回滚 | 当前主链保留，后端/浏览器首轮已验；历史普通角色页面缺口本轮补修 |
| [2.0.3](../releases/v2.0.3-stable.md) | 会话令牌 Base64URL 规范校验、防篡改回归 | 身份底座保留，无新增页面；应以当前安全测试和跨用户验证为证据 |
| [2.1](../releases/v2.1.0-stable.md) | Agent Runtime，4 类任务、队列、事件/SSE、取消、重放、审批幂等与写白名单 | 后端 `/agent-runs` 与旧组件留存；**生产默认关闭**；本次复用旧组件恢复 `/agent-lab`，管理员且编译/runtime 同时启用才可进入。本次合成环境实证真实 Redis 入队→取消→深链回读；未运行独立 Worker，不计作生产启用或完整审批执行验收 |
| [2.2](../releases/v2.2.0-stable.md) | 地图质量 steward、指定人员开关、暂停与紧急停止；最多 100 个真实资产，审批二次校验，审计指标 | `/agent-map-steward` 与 AgentCenter 旧面板保留；当前生产停用实验室；显式启用后从 `/agent-lab` 访问，不以管理员新运行中心代替验收 |
| [2.3](../releases/v2.3.0-stable.md) | 案件零写入预检；案件质量 steward、指定人员、最多 30 案、采纳指标 | **预检在案件录入主链保留**；steward 是可选旁路。本次修 Cases 发起后误跳 `/agents`，改为 `/agent-lab?runId=...` 并由旧面板独立读取指定任务，新建任务的 runId 深链已真实回读匹配；案件页 steward 跳转修正另由路由回归覆盖 |
| [2.4](../releases/v2.4.0-stable.md) | 双域 steward、案件/资产显式选集、入队前范围验证、空间参考与只读证据报告 | `/agent-dual-domain` 及 `/agent-lab` 旧面板保留；生产关闭。v3 自动双域是后续业务替代，不能将其通过数复用为旧 steward UI 通过 |
| [2.5](../releases/v2.5.0-stable.md) | Agent 运行成功/降级/失败率、耗时、调用/token/成本、模型目录 | 旧 Agent 观测与成本仪表在受控 `/agent-lab` 恢复；当前 `/agents` 独立展示 v3 版本/评测概览；安全目录不得泄漏模型配置 |
| [2.6](../releases/v2.6.0-stable.md) | 经验资产/报告快照版本化、来源签名、draft→confirmed/archived、跨案复用及采纳审计 | `/case-intelligence` + knowledge services 保留；实际按钮调用生成、复核、采纳/不适用、报告快照，viewer 只读；当前后端与工作台闭环回归涵盖 |
| [2.8](../releases/v2.8.0-stable.md) | 今日研判工作台、每案一个下一步、四段进度、跨页会话、30 日效率度量、角色隔离 | `/workbench`、全局 ActiveWorkSessionBar；POST 开始/完成/放弃，GET 恢复/指标。viewer 仅跳转、不采集会话；需实际验证跨页及后端持久化 |
| [2.9](../releases/v2.9.0-stable.md) | 单案六层证据走廊、稳定 data_version、失效引用和断链队列、层开关/检查器/摘要导出 | `/graphs/evidence` → `GET /graphs/evidence/{case_id}` 保留；工作台可带 caseId 直达；只读，不以空间邻近当事实 |
| [3.0](../releases/v3.0.0-stable.md) | 相邻时间窗口态势、热点变化、重点井关注、最多 3 项重点、离线沙盘、Markdown 简报 | `/situation` → `GET /situation/overview` 保留；空窗口不制造泛化建议；导出为本次读取结果 |
| [3.6：地理底座](../releases/v3.6.0-stable.md) | 来源、Excel/CSV 模板、坐标转换、异常隔离、厂区权限、资产版本 | `/jurisdiction` 内 MapDataGovernance、辖区资产及地图服务保留；管理员导入/编辑，普通账号只读资产；本次修禁用入口 |
| [3.6：离线地图](../releases/v3.6.0-stable.md) | 受控公共包、瓦片逐项验包、生产快照、内网瓦片、发布与回滚 | 辖区地图治理面板及 `/cases/map` 等消费者保留；历史公网同步关闭是当前安全边界，不能算缺少已启用生产能力 |
| [3.6：案件治理](../releases/v3.6.0-stable.md) | 事务 Outbox、自动标准画像、最多 3 项关键缺失、回填、幂等/恢复 | 案件保存后管道，页面展示画像与关键缺失；与旧 Agent Lab 无依赖；真实 Redis/Worker 恢复以运维核验为准 |
| [3.6：自动双域](../releases/v3.6.0-stable.md) | 画像+地图版本绑定，每案最多 3 个区域候选，支持/反向证据/信息缺口 | 案件/态势成果入口、画像与候选服务保留；不能把候选当正式结论，不新建执行任务 |
| [3.6：态势参谋](../releases/v3.6.0-stable.md) | 每日/每周部署参考、技防摘要、最多 3 项建议与反馈 | 态势、辖区参考/反馈及后台定时任务保留；是否按目标服务器时钟定期产生仍需服务器运行证据 |
| [3.6：统一治理](../releases/v3.6.0-stable.md) | 算法/范围版本、评测、影响网格重算、覆盖沙盘、管理员运行中心 | `/agents` IntelligenceRuntimeCenter 与治理/评测 API 保留；本次去除误绑旧实验室开关，仍管理员专用 |

相对 v1 新增的 6 个既有路由是 `/workbench`、`/graphs/evidence`、`/situation`、`/settings/users`、`/case-review`、`/showcase`；最后两项属于后续版本，在主报告验证。本轮另恢复第 7 个受控兼容入口 `/agent-lab`，故当前共 30 个业务路由。`/showcase` 关闭时明确提示，不能因为可显示提示就算展示业务完成。

## 前端实际动作到 API 的核验点

| 业务链 | 实际调用 / 结果 | 本次前端证据与应做的真实动作 |
|---|---|---|
| 模型配置→会议模板→发起→报告→结论 | Settings `/models` 增改删/设默认；Meetings 安全目录 `/meetings/model-options`；模板 POST 创建/使用；POST `/meetings`；GET 会议及 conversations/analyses/rankings/report；POST `/conclusions/from-meeting/{id}` | 新增会议 4 项回归：列表外深链接、分析员不读管理配置、viewer 写入禁用、处理中不提前取报告及错误态。浏览器应以本地模拟模型演练完整链并回读，不触发外部模型 |
| 报告打开和复核 | `/reports?meetingId=...` 独立取目标会议；会议报告 GET；审稿 POST | 首轮报告 5 项回归；须验证列表外历史报告正文以及复核状态回读，不能只验证按钮存在 |
| 结论生成/草稿/复核 | `/conclusions/generate`、`/draft`、`/from-meeting`、列表/详情、`/{id}/review` | 新增 3 项回归；viewer 生成与复核禁用、分析员保留、错误不显示缓存记录；复核会刷新详情缓存 |
| 事件→案件→工作台 | POST `/events/`；POST `/events/{id}/convert-to-case`；跳 `/cases?caseId=...`；GET `/workbench/today` | 新增事件 3 项回归；需实际验证转案件只产生正确目标、列表关联与跳转一致 |
| 条件组→详情→热力/时间线 | GET `/gangs/statistics`；POST `/gangs/identify`、`/{index}/activity-heatmap`、`/timeline` | 本次修筛选编辑值与已显示结果混用、失效已选组索引、viewer 自动 POST；“新建档案”改“查看当前画像”。组别只是条件聚类 |
| 关系图谱/证据走廊 | POST `/graphs/serial`；GET `/graphs/evidence/{case_id}`；点击节点/连线、层开关、导出 | 关系生成 viewer 明确禁用；证据走廊为只读替代查看入口；本次补静态权限回归，图谱算法门禁另跑链条测试 |
| 工作台跨页会话 | GET `/workbench/today`、`/sessions/active`、`/metrics`；POST `/sessions`、`/{id}/events` | 代码核对：管理员/分析员计时，viewer 只跳目标；会话完成/放弃由用户明确操作。主浏览器需覆盖开始→跨页→完成/放弃→指标回读 |
| 当前助理 | POST/GET `/intelligent-queries`，续问 parent、取消、文档下载 | 当前是 v4 查询能力，已有独立测试和首轮真实闭环；旧 `/assistant/chat` 的留存 API 应由后端单独测试，不标为当前聊天 UI |
| 辖区配置与分析 | GET 授权厂区、资产、快照、质量、案件风险上下文、相似点、经验、briefing；POST 资产/导入/反馈/部署参考 | 本次统一 asset admin-only 前端入口，viewer 不请求生成参考；MapDataGovernance 已按 admin 控制。地图导入/发布/回滚需合成包实际验收 |
| v3 运行中心与旧 Lab | 当前 `/agents` → GET `/admin/intelligence-runtime/overview` + 评测服务；旧 Lab 组件在受控 `/agent-lab` 复用 | 新增路由/导航回归证明新运行中心不依赖 Lab 开关、旧 Lab 只向明确启用的管理员开放。根代理另验兼容页面，不能把两种页面视作同一能力 |

## 本轮确认并修正的前端问题

1. 会议普通账号读取管理员模型/会议配置导致 403 且无法选择模型。改读四字段安全目录，配置提示仅管理员读取，保留 analyst 发起能力。
2. 会议深链接必须在默认 100 条内；改为按 meetingId 独立 GET。服务端已倒序，移除前端再次反转；“本月”误标改为“本页”。会议状态按组件生命周期轮询，报告只在完成后获取。
3. 会议、事件、结论、图谱与辖区页面暴露必被后端拒绝的只读/普通账号写操作。按既有后端权限禁用并解释；未放松服务端权限。
4. 会议/事件/结论接口错误被混为成功空态，结论复核后详情缓存不更新；补错误态和失效刷新。
5. `/agents` 当前是 v3 管理员运行中心，却被旧实验室开关门控；恢复独立管理员入口。旧 Lab 复用已有组件恢复 `/agent-lab`，修正案件发起后的任务深链接；生产仍关闭实验室。
6. 条件组“新建档案”只打开详情；改为准确操作名。筛选参数变化不再立即拿新参数解释旧聚类结果，失效选择不会发 index=-1 热力请求。
7. 巡逻地图 4 条固定路径被称作 AI 自动规划；改永久明确标注“固定示意、路线待配置”，不声称真实计算路线。

8. 新侧栏重写过程中丢失运行版本展示；保留新布局，恢复账号区版本标识及仓库版本回退。
9. 案件油量标签“吨或升”与后端吨口径不一致；改为“吨，仅填写核定吨值”，配合后端保留原始升值、没有密度不换算的修正。

## 自动化验证记录

- 本批前端：**72 个测试文件，330 项通过**；本轮新增 5 个文件、20 项，覆盖上述会议/事件/结论/历史边界。类型检查通过。
- 默认参数生产构建通过；链条回归 **4 项通过**，运行版本门禁 **3 项通过**；每个执行步骤的完整日志和真实退出码保存在本机私有目录 `/tmp/aicommander-frontend-audit.sjpG6D/legacy-current-{test,typecheck,build}.log` 及对应 `.exit`，链条为 `legacy-chain`，版本为 `legacy-release-version`。
- 早期测试有模拟数据缺失字段造成的失败，修正测试夹具后全量通过；一次构建因其他任务同时重写 Layout 而遇到中间状态的类型错误，保留并发修改、适配当前布局后重新验证；新布局恢复运行版本标识以满足既有发布门禁，独立 light/dark 配色变更对应的旧同色断言已改为有效颜色与悬停态检查；另一次从仓库根目录误调用前端命令退出 254，记录保留，未计为成功。编译曾提示安全模型目录已移除 model_name，前端已统一仅使用安全 name 字段。

## 真实浏览器历史补验

根代理执行的 [10 条历史业务结果](../../output/legacy-verification-2026-09-12/browser-result.json) 已实证 `passed=true`：模型配置新增/默认/编辑回读、会议模板、102 条历史会议中最早报告的 Markdown 下载与会议深链接、事件转案件及幂等回读、工作台会话开始/跳转/放弃、关系图谱 PNG 下载、证据摘要下载、条件组详情、兼容人员录入、兼容重点部位录入。页面 JS 错误与非预期 HTTP 错误均为 0；完整执行日志为 [browser-final.log](../../output/legacy-verification-2026-09-12/browser-final.log)。这些使用临时合成数据库，没有外部模型调用。

该轮还发现设置页多个表单复用了 DOM 字段 ID，导致人员/重点部位标签错误关联隐藏字段；根代理为模型、人员和重点部位表单配置唯一名称，3 项设置回归与默认构建通过。并行后端最终全量报告为 1877 项通过、39 项跳过；跳过项不能算本轮执行通过。

独立 Lab 浏览器先实测出缺少 Redis 的提交返回 503，正确提示队列不可用，没有冒充排队成功。证据保留在 [lab-browser-result-attempt-4.json](../../output/legacy-verification-2026-09-12/lab-browser-result-attempt-4.json)。产品提交前要求 Redis ping，单配置 Celery 内存 broker 无法替代该前置。随后使用独立 Redis 完成正向链，任务 `60807953-1f81-4163-98f5-7c84aec0dc82` 仅选合成资产 `1`，创建响应及独立 API 回读均为 `queued`；取消后同一 ID 回读 `cancelled`，`/agent-lab?runId=60807953-1f81-4163-98f5-7c84aec0dc82` 能恢复该详情，模型调用 0 次、源资产未变。根代理只读核验隔离 Redis 的 `agent_lab` 队列长度为 1，见 [队列证据](../../output/legacy-verification-2026-09-12/redis-queue-evidence.json)。未启动 Worker，因此不把真实入队称为规则执行完成；未取得独立 broker task ID。

本轮采用分段实证，见 [6 项结果索引](../../output/legacy-verification-2026-09-12/lab-browser-evidence-index.json)。第一次正向执行已通过入队、取消深链、v3 中心与分析员模型下拉，后因测试使用 exact 文本定位带子按钮的地图提示而退出 1；[原结果](../../output/legacy-verification-2026-09-12/lab-browser-result.json) 和 [原日志](../../output/legacy-verification-2026-09-12/lab-browser-run.log) 保留其 `passed=false` 和真实退出码。只修改测试定位后，使用新浏览器上下文补跑 4 项只读流程，结果 [passed=true](../../output/legacy-verification-2026-09-12/lab-browser-readonly-result.json)，[日志](../../output/legacy-verification-2026-09-12/lab-browser-readonly.log) 退出 0：`/agents` v3 独立可读；analyst 可选择安全目录的主持/分析模型且无管理 403；analyst 访问 `/agents` 与 `/agent-lab` 均被权限路由拦截；viewer 的会议、事件和结论写入口禁用。只读补跑除登录外没有业务写请求，没有新建第二项任务。

分析员权限重定向的大屏没有合成地图快照：精确 manifest 请求返回 404、正文“地图版本不存在”，同时严格确认可见的状态提示“底图未配置或加载失败；当前覆盖物不代表底图完整，请联系管理员。”及重试按钮，见 [权限与地图空态截图](../../output/legacy-verification-2026-09-12/lab-browser-analyst-admin-routes.png)。该环境状态单列；其余 HTTP 错误和页面 JS 错误均为 0。重启后的合成库仅初始化两条无外部连接的主持/分析模型目录记录（ID 103、104），未发起模型会议或调用外部服务。

## 仍须区分的局限

- 本清单的静态映射和模拟回归不等于真实模型效果或目标服务器验收；浏览器和持久化结果应引用主报告对应证据。
- 生产关闭的奖金、旧巡逻、人员/重点部位、旧 Agent Lab 分别列作可选/兼容，不合并进正常生产功能通过率。兼容模式通过也不能写成生产启用。
- 旧自由聊天界面不在当前路由中，当前查询页面不能证明旧聊天 UI 已恢复。旧 Agent 实验室及成本仪表虽在 `/agent-lab` 恢复受控入口，但真实独立 Worker、外部 SDK 模型调用与现场审批效果仍需独立环境证据。
- 会议列表默认 100 条、事件列表默认 100 条、近期图谱选案 50 条等仍有样本范围。定向历史会议和报告可直接读取，未宣称列表已有完整分页。
- 固定巡逻地图只做示意透明化，未新增道路规划、档案创建或执行平台业务。
