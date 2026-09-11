# 前端预构建包交付

用途：把已测试的生产构建打成独立镜像，内网运行不需要Node、npm或开发目录。
它不替代源代码构建和验证，也不会自动确认版本达到Stable。

## 构建

先在受控构建环境从同一发布源码执行`cd frontend && npm run build`。
需要管理员Agent入口时，必须在这次前端构建前显式设置`VITE_ENABLE_AGENT_LAB=true`；
默认false，部署时只改后端环境变量不会改变前端编译开关。

在`frontend`目录打包：

```sh
docker build --pull=false --network none -f Dockerfile.prebuilt \
  -t aicommander-frontend:<已核对的版本> .
```

专用忽略文件只允许`dist/`、Nginx配置和构建描述进入上下文，
不会复制`.env`、源码、node_modules、数据库或密钥。
基础Nginx镜像使用固定摘要；构建器仍可能核对镜像元数据，因此最终内网应导入准备好的镜像，
不要把`--network none`理解为禁止构建器访问镜像仓库。

## 部署

导出并校验镜像后，经受控交换路径传入内网；沿用生产Compose和`DEPLOY_IMAGE_MODE=prebuilt`。
前后端版本、镜像摘要与验证记录必须匹配，不能挂载旧`dist`覆盖新镜像内容。
公共地图/路网及生产数据仍在独立受控卷，不写进前端镜像。

## 当前候选证据

`aicommander-frontend:4.5-closeout-candidate`清单摘要：
`00371a26e99e492cadf5776523e84fb32f39bf55fdc420c55b58cde9e277e337`。
它包含态势图表完整生命周期修复，Agent入口使用默认关闭构建。
当前发布状态和双镜像验证以[收口核对](../docs/validation/v4.5-closeout-audit.md)为准。
## 历史候选说明（2026-09-11）

态势兼容面板同步折叠/卸载修复后的候选镜像清单为
`ae85b84bfa081e785001e2925f4ab39c80bd7121f376cc1aab0e7cd3069fe9ec`。
该构建曾通过单轮HTTPS案件路径和Word/PDF下载，但后续复测发现图表白屏，不能作为修复完成证明。
更早的空态修复候选为`6fa61a20d809d802ee4c5058d2468f535f16d1b51d79acd6bdf52b3c9402a74f`。
这些历史候选均已被当前候选替代；具体失败及修复过程保留在收口核对记录中。
