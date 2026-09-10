# 联网区公共地图月度检查

仅部署在联网采集区，不安装在案件服务器，不挂载内网文件或配置。
检查黑龙江、吉林、内蒙古三个固定Geofabrik公开提取的校验小文件；不接受任意URL，
不读取案件、井位、用户问题，不下载PBF、不构建或发布地图。

首次检查标记 `initial_candidate`，后续按上次检查摘要区分 `changed`、`unchanged`。
这不是与内网已安装地图的自动比较；MD5仅作为提供方变更提示，不能替代候选原文件的SHA256校验。
检查失败保留旧摘要并标记 `failed`，不报为“没有更新”，本月可重试。
同一UTC月份成功后默认不再联网；人工需要复查时使用 `--force`。

管理员在专用Linux采集机上创建无登录账号 `aic-map-collector`，将
`scripts/check-public-map-updates.py` 复制到 `/opt/aicommander-public-source/`（root只读管理），
再将本目录两个systemd文件安装到 `/etc/systemd/system/`。
经联网区管理员确认后启用 `aicommander-public-map-check.timer`。
模板未在本机安装或启用，不代表目标机定时服务已验证。

检查状态保存在 `/var/lib/aicommander-public-map-updates/public-update-state.json`，
每次尝试另有不可覆盖的 `check-*.json`。人工查看：

```sh
systemctl status aicommander-public-map-check.timer
journalctl -u aicommander-public-map-check.service
```

更新候选须走既有“固定同一日期的三来源 → 下载核验 → 原始对象合并/引用审计 →
显示地图与独立路网源 → 完整资产包验收”的流程。`latest`只用于发现变更，
不能把不同日期的三个来源随意混成已验收包。检查报告不是可直接导入内网的地图包。
候选包通过受控交换进入内网，现场验证后由已有发布机制处理；失败继续使用旧版地图。
