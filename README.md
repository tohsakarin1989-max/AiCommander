# AiCommander v2.4.0-stable

涉油案件数智研判与防控辅助系统。围绕案件资料治理、模式识别、时空规律、链条线索、
热点区域、研判报告和部署建议提供辅助能力，所有 AI 结论均保留人工复核边界。

## 主要能力

- 案件录入、批量导入、保存前预检和信息质量检查
- 案件标签、相似条件、时空规律和区域画像
- 案件关系图谱、链条线索及人工确认
- 多模型圆桌研判、结论复核和报告生成
- 待办中心、批量复核和经验卡沉淀
- 井点、管线、技防设施等辖区业务底座
- 用户、角色、会话、审计和加密模型配置

## 技术栈

- 后端：Python 3.12、FastAPI、SQLAlchemy、Alembic、Celery
- 前端：React 18、TypeScript、Ant Design、ECharts、Vite 8
- 生产数据：PostgreSQL 16、Redis 7
- 生产入口：Nginx、Docker Engine、Docker Compose Plugin

## 本地开发

Docker 开发环境：

```bash
./start.sh
```

访问：

- 前端：<http://localhost:3000>
- 后端 API：<http://localhost:8000>
- 开发接口文档：<http://localhost:8000/docs>
- 首次初始化令牌：`dev-bootstrap-token-change-me`，仅限本机开发

停止：

```bash
./stop.sh
```

SQLite、本地前后端和测试命令见 [QUICKSTART.md](./QUICKSTART.md)。

## 生产部署

开发用 `docker-compose.yml` 包含源码挂载和热重载，不能用于服务器生产上线。生产部署使用：

```bash
sh ./scripts/init-production.sh
sudo sh ./scripts/deploy-production.sh
```

生产版本包含：

- PostgreSQL 16、Redis 7、后端、Celery、前端五服务编排
- 所有业务 API 和 WebSocket 登录保护
- 管理员、分析员、只读账号三级权限
- HttpOnly 安全会话、登录锁定、来源检查和写操作审计
- 模型与系统密钥加密存储和掩码返回
- SQLite 到 PostgreSQL 的受控数据迁移脚本
- HTTPS 反向代理样例、部署预检、升级前自动备份、迁移版本健康检查
- 日志轮转和固定基础镜像 digest

完整安装、下载来源、旧数据迁移、HTTPS、备份恢复和回滚步骤见
[服务器部署与运维手册](./docs/server-deployment-runbook.zh-CN.md)。

## 可选 Agent Lab

“油盾·双域研判智能体”作为独立可选辅助层，默认关闭，不参与核心系统就绪判定。默认由内网规则引擎运行，
不需要模型密钥，也不会向外部发送数据。当前提供案件数据质检、
地图数据质检、双域融合研判、证据成果物、运行轨迹和管理员审批；Agent 不直接修改案件，地图候选也只有
在 `assist` 模式、写入开关和人工审批同时满足时才能通过现有业务服务执行。
v2.4 完整继承两个数据管家，并将双域融合研判和综合证据报告开放为指定人员只读试用。双域任务必须
同时明确选择案件和有效地图资源，单次默认最多 10 起案件、100 项资源；只生成案件—生产目标距离、
历史聚合热点、事实、推断、建议、信息缺口和证据索引，不预测犯罪、不自动确认串并案、不自动派发
巡逻，也不生成正式数据写入操作。系统默认仍不需要 OpenAI 或其他模型 API。

部署开关、数据出域、故障降级、评测 Harness 和八周验收门槛见
[Agent Lab 部署与验收手册](./docs/agent-lab-runbook.zh-CN.md)，竞赛现场记录使用
[竞赛冻结与演示清单](./docs/competition-demo-checklist.zh-CN.md)。

## 验证

```bash
cd backend
python -m pytest

cd ../frontend
npm run typecheck
npm run test
npm run build
```

当前 `v2.4.0-stable` 已通过后端 265 项、前端 22 个测试文件共 93 项测试，以及类型检查、
生产构建、依赖审计、全新数据库迁移、真实浏览器链路和隔离生产部署演练。完整发布门禁见
[v2.4.0-stable 发布说明](./docs/releases/v2.4.0-stable.md)。

## 项目结构

```text
AiCommander/
├── backend/                       # FastAPI、Alembic、Celery、测试
├── frontend/                      # React 前端和容器内 Nginx
├── deploy/nginx/                  # 宿主机 Nginx 样例
├── docs/                          # 设计、计划和部署手册
├── scripts/                       # 生产初始化、部署、数据迁移
├── docker-compose.yml             # 本地开发
└── docker-compose.production.yml  # 生产部署
```

`docs/submission-materials/` 为本地私有材料目录，不随仓库发布。
