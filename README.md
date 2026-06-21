# AiCommander

涉油案件数智研判与防控辅助系统。

AiCommander 面向案件管理、线索研判、模式识别、报告生成和指挥展示，帮助保卫、研判和管理人员把分散案件信息整理成可复核的业务判断。系统定位是“研判辅助”，不替代人工确认、执法审批或现场处置。

## 核心能力

- 案件台账：录入、编辑、检索案件基础信息、涉案车辆、人员、证据和处理状态。
- 质量复核：识别案件材料缺口、奖金核算材料门禁和待人工确认事项。
- 链条研判：围绕作案手法、地点条件、时空规律、车辆工具和链条线索生成关联提示。
- AI 研判辅助：支持案件结构化预处理、研判包、报告草稿、结论草稿和引用依据整理。
- 知识沉淀：把已确认经验卡、案例标签和报告结论作为可检索知识资产。
- 指挥展示：提供案件态势、热点区域、链条地图和运营指标展示。

## 功能边界

系统不会默认扩展为巡逻执行平台、红色网格流程平台、警企联动闭环平台或通用综合管理平台。对已抓获、已处理案件的关系研判，优先分析作案手法、地点条件和链条线索，不机械套用“同人同车跨多案复现”。

所有 AI 输出均应作为草稿或建议使用，关键结论、标签、经验卡、报告和奖金核算结果必须经过人工复核。

## 技术架构

```text
AiCommander/
├── backend/                 FastAPI 后端、SQLAlchemy 模型、业务服务、异步任务
│   ├── app/api/             API 路由
│   ├── app/services/        案件、链条、报告、知识和自动化服务
│   ├── app/models/          数据模型
│   └── tests/               pytest 回归测试
├── frontend/                React + TypeScript 前端
│   └── src/pages/           案件、地图、报告、大屏和设置页面
├── docs/                    设计说明、路线图和版本管理文档
├── docker-compose.yml       可选 PostgreSQL/Redis/Docker 启动配置
├── .env.example             本地环境变量模板
└── VERSION                  当前公开基线版本
```

主要技术栈：

- 后端：Python 3.10+、FastAPI、SQLAlchemy、Alembic、pytest
- 前端：React 18、TypeScript、Vite、Ant Design、ECharts、Leaflet
- 可选基础设施：PostgreSQL、Redis、Celery、Docker Compose

## 快速启动

### 方式一：SQLite 本地运行

适合快速体验和后端开发，不依赖 Docker、PostgreSQL 或 Redis。

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python init_db.py
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

新开终端启动前端：

```bash
cd frontend
npm install
npm run dev
```

默认访问地址：

- 前端：http://localhost:3000 或 Vite 输出的本地端口
- 后端 API：http://localhost:8000
- API 文档：http://localhost:8000/docs

### 方式二：Docker Compose

适合集成测试或接近部署环境的本地运行。先创建本机 `.env`，真实值不要提交。

```bash
cp .env.example .env
python3 - <<'PY'
from pathlib import Path
import secrets

path = Path(".env")
text = path.read_text()
text = text.replace("<generate-a-local-database-password>", secrets.token_urlsafe(24))
text = text.replace("<generate-a-local-secret-key>", secrets.token_urlsafe(32))
path.write_text(text)
PY

docker-compose up -d
```

停止服务：

```bash
docker-compose down
```

### 方式三：交互式本地脚本

```bash
./setup_local.sh
```

脚本会检测 Python、Node.js、Docker，并按选择启动 SQLite 或 Docker 相关服务。

## AI 模型配置

AI 能力是可选项。未配置模型密钥时，系统仍可运行基础案件管理和确定性规则能力。

推荐把密钥放在本机环境变量或 `backend/.env` 中：

```bash
SECRET_KEY=<generate-a-local-secret-key>
OPENAI_API_KEY=<your-openai-api-key>
ANTHROPIC_API_KEY=<your-anthropic-api-key>
```

不要把真实密钥写入代码、文档、截图或提交历史。

## 测试与构建

后端关键回归：

```bash
cd backend
source venv/bin/activate
PYTHONPATH=. pytest
```

前端测试、类型检查和构建：

```bash
cd frontend
npm test
npm run typecheck
npm run build
```

涉及链条研判、地图连线或指挥大屏时，优先补跑：

```bash
cd backend && PYTHONPATH=. pytest tests/test_chain_analysis.py -v
cd frontend && npm run build
```

## 版本管理

当前公开基线版本：`1.0.0`

分支规则：

- `main`：稳定公开版本，只放可发布代码。
- `develop`：日常集成分支。
- `feature/<short-name>`：从 `develop` 拉出的功能分支。
- `fix/<short-name>`：从 `develop` 拉出的修复分支；紧急发布修复可从 `main` 拉出。
- `vMAJOR.MINOR.PATCH`：发布标签，打在 `main` 上。

详细说明见 [docs/VERSIONING.md](docs/VERSIONING.md)。

## 安全与隐私

- `.env`、数据库文件、办公材料、真实案件数据、本地助手配置不会进入 Git。
- `.env.example` 只保留占位符，不包含可复用口令。
- 本地默认使用 SQLite；生产和联调环境必须显式设置 `SECRET_KEY`、数据库连接和模型密钥。
- 公开提交前应扫描密钥、个人信息、数据库文件和办公文档。
- `docs/submission-materials/` 是本地私有材料目录，已排除出 Git。

## 文档入口

- [QUICKSTART.md](QUICKSTART.md)：启动方式、测试命令和常见问题。
- [docs/README.md](docs/README.md)：路线图、大模型接入边界和设计参考。
- [docs/VERSIONING.md](docs/VERSIONING.md)：分支、标签和发布规则。

