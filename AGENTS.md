# Repository Guidelines

## 项目边界
- 本项目定位为“涉油案件数智研判与防控辅助系统”，功能迭代要先判断是否符合这个树干，再决定是否扩展枝叶。
- 优先做案件分析、模式识别、时空规律、链条线索、热点区域、报告生成和部署建议。
- 不要默认扩成巡逻执行平台、红色网格流程平台、警企联动闭环平台或通用综合管理平台。
- 对已抓获、已处理案件的数据，关系研判优先围绕作案手法、地点条件和链条线索，不要机械套用“同人同车跨多案复现”。

## 项目结构与模块组织
- 核心后端位于 `backend/app`：`api` 存放 FastAPI 路由，`services` 聚合业务逻辑，`repositories` 处理持久化，`models` 定义 SQLAlchemy 实体，`tasks`/`ai` 承载异步与大模型调用。数据库迁移配置在 `backend/alembic`。
- 前端位于 `frontend/src`：`pages` 对应页面视图，`components` 复用组件，`services` 统一封装 HTTP/状态管理，样式入口 `index.css`。Vite 配置在 `vite.config.ts`。
- 测试入口位于 `backend/tests`；当前与本周链条研判迭代直接相关的用例包括 `test_case_service.py`、`test_chain_analysis.py`，默认使用内存 SQLite。

## 构建、测试与开发命令
- 一键启动（Docker 全栈）：在仓库根目录执行 `./start.sh`（等价 `docker-compose up -d`），停止用 `./stop.sh` 或 `docker-compose down`。
- 本地后端开发：`cd backend && source venv/bin/activate && uvicorn app.main:app --reload`。首次需要 `pip install -r requirements.txt` 并运行 `python init_db.py`；如涉及模型或表结构改动，先执行 `alembic upgrade head`。也可使用 `backend/start_backend.sh` 自动检查连接并初始化。
- 前端开发：`cd frontend && npm install && npm run dev`（默认 http://localhost:3000），构建产物 `npm run build`，本地预览 `npm run preview`。
- 后端测试：`cd backend && source venv/bin/activate && pytest`。如依赖外部数据库，请先设置 `DATABASE_URL` 和 `REDIS_URL`。
- 本周涉及链条研判、地图连线或相关回归时，先读 `docs/superpowers/specs/2026-05-08-upgrade-roadmap.md`，至少补跑 `pytest tests/test_chain_analysis.py -v` 与 `cd frontend && npm run build`。

## 编码风格与命名约定
- Python 按 PEP 8 使用 4 空格缩进；路由模块 `app/api/<domain>.py`，服务层 `app/services/<domain>_service.py`，模型/仓库对应单复数保持一致；环境变量全大写下划线（如 `SECRET_KEY`、`DATABASE_URL`）。
- TypeScript/React 组件使用 PascalCase 文件名（如 `CaseList.tsx`），hooks/store 采用 camelCase 导出；保持类型声明完善，API 调用封装在 `frontend/src/services`，避免组件内散落硬编码路径。
- 当前未强制格式化工具，提交前请自行运行格式化（如 black/ruff 或 prettier）并保持 import 有序。

## 测试指南
- 使用 pytest，新增用例放置于 `backend/tests`，文件与函数命名 `test_*.py`/`test_*`。优先通过 in-memory SQLite/fixtures 隔离数据库，必要时模拟外部服务。
- 覆盖重点：编号/状态计算、案件流程服务、任务调度与模型调用边界条件。新增 API 请补充至少一个成功与一个失败路径。
- 前端暂无现成测试栈，新增复杂交互时请附带最小复现步骤或截图；如引入测试，请统一采用 Vitest + Testing Library。

## 提交与 Pull Request 指南
- 建议采用简明前缀型提交信息（例：`feat: 增加案件批量导入接口`、`fix: 修复会议记录分页`）；同一逻辑变更保持一次提交，避免将格式化与功能混合。
- PR 描述需包含变更概述、验证方式（命令或截图）、受影响的接口/页面，以及新增的环境变量或迁移步骤。若关联任务，请在标题或描述中引用 Issue/需求编号。
- 提交前确认本地测试通过、无敏感配置泄露（API Key/密码），并更新相关文档或示例请求。

## 安全与配置提示
- 默认支持 SQLite，本地开发无需显式 `DATABASE_URL`；生产/联调需设置 `DATABASE_URL`、`REDIS_URL`、`SECRET_KEY`，并按需提供 `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` 等模型密钥。
- 不要将密钥写入代码或提交到仓库，可使用 shell 环境变量或 `.env`（自行管理忽略）。
- 如果使用 Docker，请确保 `docker-compose.yml` 中暴露端口符合本地安全策略，并在公共环境关闭无密码的数据库/Redis。
