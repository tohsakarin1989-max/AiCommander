# v6.2 生产对象与计算资料准备验证

日期：2026-09-27。授权：完成 v6.1 后推进至 v6.2 Stable。使用现有脏工作区，不覆盖此前修复、用户演示与文档；无 Git 提交、推送或部署。

## 实施范围

- v6.1 收尾：事件关联的案件时间为未知/区间时不崩溃，不误标“窗外”；批量来源签名覆盖地点、测量、关联和原件状态，与写入使用同一字段和编码契约。
- v6.2：稳定设施身份、显式来源绑定/撤销、双时间版本、计算资料清单、共享上下文、设施侧材料关联。
- 原始案件不自动覆盖；人工材料登记不提升为犯罪事实；未核验候选与邻近分别显示。
- 身份撤销即时影响新候选消费，历史冻结成果不改；同区导入和决定统一锁序，禁止并发复活撤销值。

## 证据记录

初期 v6.1 收尾相关 68 项通过；设施 API、来源版本与档案初期联合 27 项通过。独立复核补充的旧文字引用与新修订混配、照片/PDF 依据成员关系、来源撤权异常、撤销锁序均已修复。最终联合回归记录在下文收口表；不同批次有重叠，不相加冒充独立总量。

SQLite 与本机可丢弃 PostgreSQL：`v61s01 → v62f01` 升级、原始案件与旧设施快照保留、旧有效期未知、绑定与撤销、人工材料关系外键、独立备份恢复通过。PostgreSQL 最后一次 1 项通过（3.17 秒），覆盖 Area→Identity 的实际加锁 SQL 顺序；不冒充完整并发负载测试。临时容器已清理，不涉及现用数据库。

### 最终收口

| 验证 | 实际结果 | 范围与限制 |
| --- | --- | --- |
| 后端 26 文件联合 | 284 passed，2 skipped，21.15 秒 | 身份、双时间、权限、计算准备、迁移、设施来源、案件保存/管线、链条、生产配置与健康；不是全仓测试 |
| 版本同步后补测 | 59 passed，3.26 秒 | 生产配置、观测、待办、批量复核；与联合检查有重叠 |
| 前端 11 文件 | 69 passed | 档案、身份、材料关系、准备清单、上下文、地图关联、案件/区域界面和大屏模型 |
| 类型检查与生产构建 | 通过 | 既有地图/图表大分块警告仍存在 |
| 新权限条件缓存 | 9 项固定用例通过 | 范围缩减/清空/扩大、别名、跨会话、设施转区、关联的案件与设施双亲权限均核验 |
| 当前迁移头 | 单一 `v62f01` | 只读核验，未执行现用库迁移 |

联合检查中跳过：1 项需要显式开启的 PostgreSQL 演练已另行真实执行通过；1 项旧 Word/浏览器地图渲染未开启，导出服务未改，本轮未重做该浏览器导出证据。不能把 skipped 写成 passed。

后端联合文件位于 `backend/tests`：`test_facility_identity_v62`、`test_facility_foundation_api_v62`、`test_facility_scope_v62`、`test_facility_computability`、`test_facility_migration_v62`、`test_facility_candidate_sources_v62`、`test_facility_summary`、`test_facility_dossier_content`、`test_facility_dossier_roads`、`test_facility_condition_comparison`、`test_case_facility_comparison`、`test_facility_production_conditions`、`test_facility_history_conditions`、`test_facility_document_map`、`test_facility_dashboard_scope`、`test_map_foundation`、`test_jurisdiction_context`、`test_area_scope_options`、`test_case_intake_v61`、`test_case_sources_v61`、`test_fresh_database_v61`、`test_case_service`、`test_case_pipeline`、`test_chain_analysis`、`test_production_config`、`test_observability`（`.py`），使用既有 pytest。

### 浏览器

采用现有 `serve-ui-verification.py` 的一次性合成 SQLite、24 条合成案件和 1 个设施，本机回环服务，关闭外部模型。

- 管理员在原辖区底座看到按辖区分页的计算资料清单，可打开同一设施档案。
- 历史查询北京时间 `2026-01-01 08:00` 与 `2026-02-01 08:00` 分别转成 UTC `00:00Z`，网址保留辖区、设施和两个时点。
- 缺少历史版本时显示无法确认，不回退为当前属性；当前案件/道路/成果与历史生产资料分开标注。
- 清空时间后恢复当下查询，保留辖区和设施；临时前后端与本轮浏览器已关闭。
- 截图：`output/playwright/v62-historical-facility.png`（本地合成数据，不含业务原文）。

隔离库未安装地图包，页面明确“待发布”；不把此截图当作离线地图覆盖验收。控制台仍有现有组件弃用、开发请求取消及合成环境缺少服务日志，不声称零告警。浏览器未逐一运行所有身份和材料写入路径，这些路径由前端行为测试及后端集成测试覆盖。

### 保存性能

使用开发前冻结的 v6.1 本地源码副本 `/tmp/aic-v61-baseline.X2cZ34`，不是以已发布旧提交冒充脏工作区基线。脚本 `scripts/verify-v62-save-performance.py`：每轮 200 条历史合成记录、10 次预热、50 次创建及修改，双版本交错各三轮，禁止网络。

初次与中间测量未达到相对 P95 5% 目标，保留 `evidence/v62-save-performance.json`、`v62-save-performance-optimized.json`、`v62-save-performance-final.json`。定位到新增 ORM 权限选项的查询缓存键开销；不删除权限校验或更改门槛。最终优化后的测量另列，不覆盖失败证据。

只将新增三类权限条件改为 lambda SQL，保留闭包参数追踪及别名支持；旧权限规则不变。`evidence/v62-save-performance-scoped.json` 首轮通过，但基线首轮存在明显抖动；停止临时界面服务和其他并行验证后再次测量，最终以 [安静环境记录](evidence/v62-save-performance-quiet.json)为准：

| 服务操作 | 冻结 v6.1 P95 | v6.2 P95 | 变化 |
| --- | ---: | ---: | ---: |
| 创建案件 | 16.653 ms | 16.366 ms | -1.72% |
| 修改案件 | 16.542 ms | 16.144 ms | -2.41% |

满足本次本机对照的“不退化超过 5%”目标，不将这点差异宣传为业务提速效果。每个版本每项操作累计 150 个样本，源码摘要和全部原始耗时在证据文件中；后续版本号与说明文字同步未改变保存实现。

此测量仅为本机 SQLite 服务调用，不代表 HTTP、并发、PostgreSQL 或目标服务器性能，也不追溯冒充 v6.0→v6.1 性能验收。

## 明确边界

- 未升级现用数据库，未部署目标服务器，未调用真实模型，未发送案情或生产坐标。
- 未重建地图或 Valhalla，未确认全厂入口和道路均可计算。
- 未把“资料齐备”写成“已有道路路径”；历史资料范围不包含未记录的过去现场状态。
- 未进行生产负载或长期试用；不恢复已取消的 30 天及固定真实业务样本门槛。
- 源码版本、浏览器合成流程、数据库组件验证和正式业务效果分别记录。

升级与回退说明见 [v6.2 发布说明](../releases/v6.2.0-stable.md)。
