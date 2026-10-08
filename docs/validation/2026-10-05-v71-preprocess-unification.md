# v7.1 A06：旧案件预处理入口收敛

本记录只说明本地源码与针对性验证；不代表 v7.1 整版发布、目标服务器或真实模型验收。

## 实现边界

- 单案维护、批量维护、批量复核、旧 Celery 名称兼容入口均使用 `CaseRevision → OutboxEvent → CaseAnalysisProfile`。相同源修订及规则版本复用画像，`only_missing` 不再以旧 `features` 是否为空判断。
- 告警转案件只使用案件保存时已提交的 Outbox，不同步等待模型。独立 `batch_preprocess_features.py` 改为可按游标继续的事件补齐入口，取消直接 SQLite 更新及另一套提取规则；它本身不调用模型。
- 不再新增 `PreprocessJob`。状态接口读取当前画像对应的真实 Outbox 状态，旧任务数量明确列为历史。模型调用失败不回滚已完成的标准画像。
- 不修改 `Case.features` 中的人工标签、旧摘要或历史人工确认经验。维护页分开显示当前版本、待更新的历史画像、独立模型补充及旧 JSON 历史。
- 旧 `_write_features` 私有入口明确拒绝无版本数据注入，保留 `_build_llm` 给现有录入文本预览使用。

## 独立模型补充

新增 `CasePreprocessSupplement`，唯一约束为 `case_profile_id + model_fingerprint`，关联同一案件、源修订和画像；模型与迁移中的字段已对齐，表创建并入统一 `v71d01` 迁移。

摘要、现场条件、推断、建议仍可由可信内网模型整理，不用规则摘录冒充模型摘要。输入是同修订的原文及结构化原始记录；返回结构有大小与数量上限，每条陈述核验连续原文引用。引用说明来源，不证明模型解释为事实。

模型 IO 不占案件行锁。IO 成功或失败后均重新检查当前账号、维护权限、范围、源画像及模型配置；源修改、配置更换或撤权后的迟到结果不发布。补充独立于标准画像，不覆盖原文，不自动生成正式结论或任务。同版本已保存补充只读复用。

没有可信内网摘要模型时明确 `not_enabled`；失败为 `unavailable`，规则画像仍可用。本轮只有合成模型响应契约测试，没有真实模型效果验收。

## 消费端与兼容说明

- 新增 `GET /api/cases/preprocess/profiles`（最多 100 个 ID）及 `GET /api/cases/{id}/preprocess-result`，均只读并执行当前案件范围。
- 旧 `/analysis-profile/latest` 保留原结构，增加 `freshness`、`source_revision_id`。源已变而后台未完成时返回 `updating`、响应 `is_current=false`，不修改数据库中的历史标记，也不因 GET 重算。
- 当前实际大屏是 `DailyDashboard`，其指标来自后端统一汇总，展示的是“完成研判次数”，不是“当前有效画像数”。旧 `buildDashboardModel` 除测试外无生产调用；本轮删除其中把无版本 `features` 当当前 AI 成果和必经复核的推导，未删除当前大屏统计。
- 维护页按服务端 20 条窗口查询，补齐本页或处理明确选择，不把有限窗口称为全库。账号变化清空选择，晚到的旧账号批量回执不写入新会话视图。

## 验证证据

以下用内存 SQLite 和合成数据，未访问正式业务数据。计数存在重叠，不应相加宣称不同用例数。

1. 后端 `test_preprocess_pipeline_unification.py`、`test_batch_review.py`、`test_case_management_requirements.py`、`test_automation_alerts.py`、`test_suggestions.py`、`test_case_quality_v61.py`、`test_case_pipeline.py`：117 通过。
2. 增加旧 latest API 新鲜度回归后，重跑预处理收敛、画像流水线与批量复核：47 通过。
3. 最后重跑预处理收敛与管理员维护权限：17 通过。覆盖同输入复用、旧人工 JSON 保留、读取无写入、模型失败、错误引用、源修改、模型配置变化、撤权、模型超时同时撤权、隐藏辖区和历史计数隔离。
4. 内网模型适配器 14 个普通测试通过；回环 HTTP 测试先因沙箱不允许监听失败，获得本机测试权限后单独重跑 1 通过。回环服务是合成接口，不是真实模型。
5. 前端 `casePreprocess.test.ts`、大屏模型、待办呈现、录入预检和批量复核呈现：29 通过；前端生产构建通过，只有已有大包提示。最后接口类型及失败态调整后 TypeScript 检查通过。
6. `batch_preprocess_features.py --help` 通过；`git diff --check` 通过。

本记录不替代唯一 v7.1 数据迁移、PostgreSQL 组件验证、整版收口回归或实际维护页浏览器流程。版本号及 GitHub 发布由主任务统一处理；本子项未提交、推送或改版本号。
