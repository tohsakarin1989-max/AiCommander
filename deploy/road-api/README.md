# 道路与报告组合API镜像

## 4.x当前收口候选

当前工作树迁移头为`b508c42fd75b`，两种构建入口已同步校验该版本。
本机候选`aicommander-backend-roads:4.5-closeout-candidate`清单摘要：
`9a51a5be1511f6d95d9818b9fde05137e14931e05d1099d6139d573e63548ad0`。
已在不挂载开发源码的独立PostgreSQL/Redis环境通过录入、自动画像、原生道路计算、
新目录版本自动刷新、Word/PDF、固定输入重放及备份恢复；不等同Stable发布或目标服务器验收。
记录见[4.x收口核对](../../docs/validation/v4.5-closeout-audit.md)。

以下v4.3/v4.2内容为历史发布准备与恢复证据，不是当前候选迁移头。

v4.3发布候选包含语义查询及专题文档，迁移头93e6a20fd53b；状态见
[v4.3发布说明](../../docs/releases/v4.3.0-stable.md)。候选镜像
`aicommander-backend-roads:4.3-release-candidate`的本机清单摘要为
`bc23aac611a0ec22758ef37bd8ed6ae61b08fcc69dfe7e7965cfe7ec114f74c5`。
交付时按目标架构重新核验并使用发布版本标签；以下v4.2摘要保留作历史恢复证据。

最新交付状态以[版本核对](../../docs/releases/v4.2-candidate.md)为准；以下摘要保留各阶段的真实构建证据。

使用现有报告镜像为基础，加入已验证的Valhalla原生包、所需系统运行库及当前应用/迁移。
保留LibreOffice、中文字体、Node、Playwright及本地浏览器，不以道路功能替换报告能力。

构建前准备同CPU架构的已验收DOCUMENT_API_IMAGE和ROAD_ENGINE_IMAGE；在联网构建区
安装系统运行库，完成后导出镜像到内网，运行期间不再下载安装。
使用生产Compose叠加`docker-compose.road-runtime.yml`；独立道路Worker仍由
`road-analysis` profile控制。该override让普通Celery、Beat及可选Agent Worker与API共用
同版组合镜像，避免只构建道路API后仍启动旧版普通任务代码。

一键脚本通过`.env.production`中的`ENABLE_ROAD_ANALYSIS=true`加载此override并启用专用队列。
部署、预检和备份共用同一Compose参数组；默认false保持原稳定链路。停用时先停止道路Worker，
再关闭开关，不把停止刷新页面当作停止后台任务。
断网部署设置`DEPLOY_IMAGE_MODE=prebuilt`，先导入全部启用服务的版本镜像。
脚本在迁移和服务变更之前检查本机镜像是否齐全，不执行build/pull；缺少镜像即停止。

本机Linux arm64候选已构建，镜像清单摘要：
`06e389bec15c7e65f804508146fcb3bd2a181c74e2094f273bd77d8b438b2c8e`。
构建检查确认原生包可导入、迁移头为82d5f19ec429、LibreOffice及Node可运行。
这不是完整HTTP录入、数据库升级或报告导出链路验收，也未替换任何现有业务容器。

## 离线应用增量更新

系统运行库已准备好且Python依赖不变时，可复用同架构组合运行镜像更新应用：

```sh
docker build --network none -f deploy/road-api/Dockerfile.cached \
  --build-arg ROAD_API_RUNTIME_IMAGE=aicommander-backend-roads:4.2-combined-candidate \
  -t aicommander-backend-roads:4.2-integrated-candidate .
```

交付时将基础镜像固定到已核验摘要；若依赖变化，此入口应失败，回联网构建区重新准备基础镜像，
不得在内网临时下载依赖。应用和迁移只从白名单目录复制，不包含业务数据库、地图或配置密钥。

本次离线增量构建镜像清单摘要：
`764bc0d89c3c5647147c15f3e9607ae3125c4415fa9026c1cf2a1df1bdec4243`。
该镜像在断网、只读、非root容器中通过：临时SQLite迁移到82d5f19ec429、实际认证API录入/读取合成案件、
实际中文DOCX/PDF生成和浏览器WebGL运行。验证结束临时容器已移除。
尚不表示PostgreSQL整栈、带真实地图的道路报告或案件自动流水线完整验收通过。
