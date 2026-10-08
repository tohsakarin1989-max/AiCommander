# v7.0 候选：PostgreSQL＋地图文件＋原件联合恢复

日期：2026-09-30。结论：**专用隔离组件演练通过，1 项测试、2.61 秒**。没有操作现用/demo 数据库和容器，没有下载镜像或地图。

## 环境与实际版本

- 容器：`aic-v70-validation-pg`；已核对仅回环 `127.0.0.1:15470`。
- 新建源库：`aic_v70_joint_source`；新建恢复库：`aic_v70_joint_restore`。测试先验证两库不存在，拒绝覆盖既有结果。
- 当前 Alembic 完整迁移：从空库到唯一 head **`v70s01`**。
- 演练时根目录 `VERSION` 尚为 **`6.5.0-stable`**，属于 v7.0 收口前的候选代码验证；未把尚未更新的应用标签写成已发布 v7.0。
- 合成数据：1 起案件、2 个原始修订、1 个 PNG 原件、1 个地图快照，1 个 16,384 字节 MBTiles 文件。
- 地图来自项目 `_bundle_bytes` 合成夹具，仅有 **1 像素 PNG / z0 瓦片**；不是联网采集成果，也不证明大庆/齐齐哈尔地理覆盖。

## 实际执行路径

新增自动化入口：[test_joint_restore_v70.py](../../backend/tests/test_joint_restore_v70.py)。默认跳过，只有显式授权开关与专用合成凭据才运行。

```sh
cd backend
AIC_V70_JOINT_RESTORE=1 \
AIC_V70_JOINT_EVIDENCE_DIR=/绝对路径/本次新证据目录 \
venv/bin/python -m pytest tests/test_joint_restore_v70.py -q -s
```

`AIC_V70_SYNTHETIC_PASSWORD` 仅由测试进程环境提供，不写入报告。运行需要访问获授权的本机 Docker 和专用回环 PostgreSQL；本次通过权限申请实际执行，未将模拟 Docker 输出当成真实证据。

1. 读取专用容器端口绑定，核对现有数据库名单；只新建上述两库。
2. 源库执行当前全链路迁移；调用现有案件修订和原件上传服务，调用 `OfflineMapService` 导入、构建、发布合成地图。
3. 关闭唯一应用写会话；没有为这两库启动任何 Worker。记录停写检查点 `2026-09-30T13:54:54.280098+00:00`。
4. 真实 `pg_dump --format=custom`，地图文件生成 tar 和逐文件清单；源文件前后校验一致。
5. 真实 `pg_restore --exit-on-error --no-owner --no-privileges` 恢复到新库；地图只解包到新建空目录，不覆盖源目录。
6. 读取恢复库与恢复地图，核对以下结果。

| 核对项 | 结果 |
|---|---|
| Alembic 版本 | 恢复后 `v70s01` |
| 案件编号、原文及最新来源修订/摘要 | 一致 |
| `evidence_objects.content` 字节及 SHA-256 | 一致 |
| 原件引用与案件关联、可用状态 | 一致 |
| 原件下载服务函数实际返回内容 | 与合成 PNG 相同 |
| 数据库 current 地图快照、公共包绑定和运行 manifest | 与源环境相同 |
| 从恢复目录通过 `OfflineMapService.read_tile` 读取 | `image/png`，字节相同 |
| 所有登记地图文件大小、SHA-256 | 一致 |
| 数据库恢复后使用空地图目录 | 明确拒绝，`tile_store_unavailable` |
| 源库案件、原件、current 与源地图 | 未改变 |
| 原有其他演练数据库 | 名单保持，不清空、不写入 |

原件下载验证调用了实际后端服务函数及授权范围查询，不是完整 HTTPS/浏览器登录链；该部分由其他验收分别覆盖。

## 摘要与证据位置

- 快照 ID：`f6578171-79b4-4b8b-b38a-fb17524947d8`。
- 数据库 dump SHA-256：`6076ec04364da71611786a12aea43d2af0e82b17af5b5f15bce9968103e1b5c5`。
- 地图 tar SHA-256：`75c1080862eff06c2f09112618bf0bb5017bb16422c36de6fdd35421ca572d66`。
- 原件 SHA-256：`431ced6916a2a21a156e38701afe55bbd7f88969fbbfc56d7fe099d47f265460`。
- 运行报告、dump、地图 tar、文件清单和恢复目录保存在受控本地 `output/validation/v70-joint-restore-20260930/`，不作为源码提交。
- 本次两个新合成库及证据保留供复核；测试没有自动删除数据库或证据。重复运行须使用新隔离容器/明确处理本次合成库，不能取消“库已存在即拒绝”保护。

## 未替代的验收

本次证明数据库、地图文件与数据库内原件能够按同一合成停写点联合恢复并实际读取，不证明真实地图覆盖、中文地图资源完整性、真实业务样本、现场性能、HTTPS、真实外部原件、配置密文或密钥保险库恢复。

原始来源、配置与秘密分离保管、批准维护窗口和切换仍按[当前内网运维手册](../current-intranet-operations.zh-CN.md)执行。新的隔离真实证据补充[交付清单工作包](2026-09-30-v70-offline-delivery.md)，不把文件清单核对本身改称恢复演练。
