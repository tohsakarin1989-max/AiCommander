# 大模型接入点清单

## 已真实调用 LLM 的模块

| 模块 | 文件 | 当前用途 | 后续调整 |
| --- | --- | --- | --- |
| 模型工厂 | `backend/app/ai/model_factory.py`、`backend/app/ai/llm_providers.py` | 根据 `AIModel` 配置创建 OpenAI、OpenAI-compatible、Azure OpenAI、Anthropic Chat 模型 | 保持为统一入口 |
| 模型连通性测试 | `backend/app/services/ai_model_service.py` | 调用 `llm.invoke` 验证模型是否可用 | 保持 |
| 案件预处理 | `backend/app/services/preprocess_service.py` | 将案情、字段、质量画像结构化写入 `Case.features` | 已调整为事实、现场条件、推断、建议、信息缺口 |
| 智能助手 | `backend/app/services/assistant_service.py` | 基于最近案件、报告、统计信息回答问题 | 下一步接入案件研判工作台结果 |
| 结论工厂 | `backend/app/services/conclusion_factory_service.py` | 基于案件证据链或会议报告生成结论 | 下一步优先引用结构化研判依据 |
| 地图位置研判 | `backend/app/services/map_mcp_service.py` | 汇聚村屯、道路、加油站、储油设施、天气、来路后调用 LLM | 继续保留，输出需区分事实与建议 |
| 多模型复核 | `backend/app/ai/meeting_manager.py`、`backend/app/ai/agents/*` | 多模型独立分析、互评、主持人汇总 | 降级为高级复核，不作为主线入口 |
| Agent 任务 | `backend/app/services/agent_service.py` | 根据用户目标和案件简表输出步骤、结果、置信度 | 后续改成研判辅助 Agent，避免“自动侦查”口径 |

## 使用模型能力但不是 Chat LLM 的模块

| 模块 | 文件 | 当前用途 | 后续调整 |
| --- | --- | --- | --- |
| 向量语义检索 | `backend/app/services/embedding_service.py`、`backend/app/services/vector_db_service.py` | 生成 embedding，检索语义相似案件 | 与相似条件规则结果合并展示 |

## 当前只是文案或 TODO 的模块

| 模块 | 文件 | 当前状态 | 后续调整 |
| --- | --- | --- | --- |
| 数智自动化 AI 视觉/雷达研判 | `frontend/src/pages/IntelliInspect/IntelliInspect.tsx` | 页面模拟联动，未接入真实视觉模型、雷达数据或 LLM 后端 | 后端实体化告警后再接入真实模型 |
| 轨迹 AI 预测 | `backend/app/services/trajectory_service.py` | `use_ai` 参数存在，但代码仍是 TODO | 当前不做犯罪预测，应改为“轨迹复盘/路径条件分析” |
| 案件研判工作台 | `backend/app/services/case_intelligence_service.py` | 当前为确定性规则和统计分析 | 作为 LLM 的输入依据，不让 LLM 直接替代评分 |

## 接入原则

- LLM 负责非结构化文本理解、结构化候选提取、报告表达和问答解释。
- 规则服务负责评分、相似度、证据依据、时间空间统计和边界控制。
- 所有 LLM 输出必须区分事实、推断、建议；建议不得写成已执行任务。
- 无模型、模型失败、JSON 解析失败时必须走确定性降级。
