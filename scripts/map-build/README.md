# 公共矢量地图候选构建

仅用于联网区公共数据构建，不挂载任何案件、内部井位、生产台账、技防数据或业务数据库。
依赖安装在隔离环境，见 `../map-build-requirements.txt`。

当前配置 `two-city-vector.json` 使用已验证的两市边界加 30 km 投影缓冲的包围盒。
该包围盒不是来源完整覆盖证明。原始 PBF 独立保留；显示瓦片不是计算路网。

## 固定工具

- 官方镜像：`ghcr.io/systemed/tilemaker@sha256:8996f3dac38ac59ba02d900b847b1613d9fbb3e121cf6c101c824681a276f3f5`（Linux ARM64）。
- 实际二进制：`tilemaker v3.2.0+gfacdf933f4f5`。
- 标签转换脚本：镜像内 `/usr/src/app/resources/process-openmaptiles.lua`。
- 入口直接使用 `/usr/src/app/tilemaker`，不执行带下载功能的包装流程。
- 禁止使用 `--skip-integrity`；候选构建不替代独立 OSM 限制关系检查。
- 实际运行使用 `--network none --read-only --cap-drop ALL --security-opt no-new-privileges`，2 核、4 GB、128 进程限制，临时目录 512 MB。
- 公共输入和配置只读挂载，只有新建候选输出目录可写。运行前确保输出 MBTiles 不存在，不覆盖旧候选或现行地图。

原生生成级别为 6—16。构建工具会提示超过通常 z14 的资源成本，这是明确选择，不以 z14 放大代替 z16。
配置不引用全球海岸线、冰盖或外部都市区 Shapefile；两市内陆的水域、建筑和土地覆盖来自 OSM 自身对象，来源没有的对象不会补画。

## 来源与许可

- 公共数据：OpenStreetMap contributors，ODbL 1.0，通过 Geofabrik 区域原始数据提供。
- 标签转换脚本基于 OpenMapTiles schema v3.15，版权归 KlokanTech.com 与 OpenMapTiles contributors，CC BY 4.0；使用镜像内原始脚本，未修改。
- 本项目另行提供限定范围、原生级别和无外部 Shapefile 的 JSON 配置。
- 分发候选地图及后续正式包时保留上述来源、署名和许可信息，前端地图也应显示署名。

参考：[tilemaker](https://github.com/systemed/tilemaker)、[OpenMapTiles](https://openmaptiles.org/)、[ODbL](https://opendatacommons.org/licenses/odbl/1-0/)、[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。

制包完成后至少检查 SQLite 完整性、逐级有效载荷、解码抽样、中文地名、真实区域渲染和边缘缺失；没有完成这些验收及本地样式/字体集成的候选不得发布。
