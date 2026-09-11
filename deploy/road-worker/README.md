# 道路分析处理服务（v4.2 候选）

最新PostgreSQL整栈及交付状态见[版本核对](../../docs/releases/v4.2-candidate.md)，以下是分阶段记录。

消费既有 `road_analysis` 队列，只读地图文件、通过现有业务服务写入派生成果。
使用单并发、一次预取一项、独立资源上限，仅连接内部数据网络，不发布端口。
不开启此服务不影响案件保存；Outbox任务保留，启用后由既有Beat调度续接。

## 打包与启用

先在与目标服务器相同CPU架构的构建机完成
[原生引擎构建与验收](../../backend/road-engine/README.md)，记录已验收镜像ID/摘要。
不要把候选镜像标签当成已通过原生验收，也不要直接搬用macOS上的Python包。

在受控 `.env.production` 中配置 `ROAD_ENGINE_IMAGE` 为已验收原生镜像引用，
将 `road-analysis` 加入 `COMPOSE_PROFILES`（已有profile用逗号保留）。然后构建
`road-worker` 镜像，并随同业务镜像离线导出、校验和导入；内网启动时不下载依赖。
已有公共图还必须经系统治理构图、发布且与当前授权/条件匹配；启动Worker不自动绕过这些条件。

独立启停使用既有Compose配置的 `road-worker` 服务；保持 `celery-beat` 运行。
不要通过重启整个业务系统来处理一个道路任务。停止Worker不会删除数据库任务或地图。

当前仅接入自动案件道路分析队列；API进程内的管理员原生路由/构图仍需对应运行依赖，
本Worker镜像不会自动给API安装依赖。原生镜像及完整容器业务流程尚待验收，不能据此宣布Stable。
当前先复用原生镜像运行库保持ABI一致，后续交付精简镜像须重新核对所需动态库。

## 复用本机依赖的离线组装

如果已有相同CPU架构、Python3.12且满足当前requirements的业务镜像，可选择
`Dockerfile.cached`，传入`ROAD_DEPENDENCY_IMAGE`及`ROAD_ENGINE_IMAGE`。
该路径用`--no-index`检查全部直接依赖并执行pip check，不安装缺失包；不满足就失败，
不能忽略错误。用`docker build --network none`组装，完成后统一以`python -m celery`
启动，不依赖从旧镜像复制命令入口。

本次已核对21项直接依赖并完成离线组装，Worker镜像摘要为
`sha256:8ca29adb41deb56ccf30c78b79bc027a7c20472b41ecf1dcfcf2efce4c9d2a4c`。
非root只读断网容器中，应用VehicleRouter实际运行合成图得到路线232米、
距离范围5条片段、时间范围4条片段及completed-v1。此为应用适配检查，
尚不代表真实队列消费、全流程或目标服务器验收。

后续已完成容器队列衔接：复用`verify-road-redis-worker.py`并设置
`AIC_ROAD_WORKER_IMAGE`为该镜像，两个既有场景31.69秒通过。
使用独占Redis、内部Worker网络、合成SQLite和只读公共图，实际完成任务消费、
Worker替换、Redis消息丢失后Beat恢复及单份成果生成；报告见
`output/validation/road-redis-worker-h54b6k4c/report.json`。
这仍不等于完整HTTP案件录入或PostgreSQL整栈部署通过。
