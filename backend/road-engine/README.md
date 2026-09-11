# 固定版本可达范围引擎修复（原生对照已通过）

上游：Valhalla 3.8.3，提交 `a60c7cbfc83e073f50887cd27e0109d02e6b64e5`。
`src/thor/expansion_action.cc` 原文件 SHA-256：
`8f259e28cbd669cd1026b3435eba2a446c078b691a21e05ae4bff29db717ebed`。

`valhalla-3.8.3-completion.patch` 仅修改扩展轨迹的异常与完成契约：

- 计算异常继续抛出，不把中途轨迹作为成功结果。
- 缺失图块抛出错误，不静默漏掉边。
- 用作用域清理撤销所有已登记的轨迹回调，包括距离矩阵回调。
- 正常结束后的 GeoJSON `properties` 增加
  `aicommander_expansion_contract: completed-v1`。

该标记只证明本次原生扩展正常结束，不证明现实道路资料齐全，也不把道路集合当作面积覆盖。
应用范围完整性及业务接入另行验证，不单凭此标记替换生产引擎。

## 隔离构建

在独立目录检出上述提交及其锁定子模块，校验后用 `git apply` 应用本补丁。
以该上游目录为构建上下文，使用 `Dockerfile.verify`。镜像只用于构建、原生验收，
不是业务部署镜像；构建需要下载公开依赖，不挂载业务库、案件或生产地图。
运行验收时关闭容器网络，只挂载合成资料或已授权的公共图。

已完成真实编译、成功计算与中途异常检查、异常后同 Actor 再次调用。
交付前仍需应用适配及距离/时间可达范围集成，不把原生对照通过等同于整版验收。

## 对照验证

`scripts/verify-road-engine-completion.py --prepare <独占目录>` 创建两组互不连接的
合成道路；验证模式读取该PBF并在另一个新目录编译。原版运行时传入
`--expect-legacy`，确认普通路线在thor层报442，而扩展接口错误地返回部分轨迹。
候选版不传该选项，必须抛出同一个442，并在同一Actor上继续成功完成距离和时间扩展、
返回completed-v1标记。每次使用新的输出目录，保留构建日志和report.json。

已完成原版对照：`output/validation/engine-completion-v1/upstream-check/report.json`。
这证明故障样例能触发被补丁覆盖的路径，不代表候选版已经通过。

候选版实测已通过：`output/validation/engine-completion-candidate-xgwYhf/native/report.json`。
在断网、非root、只读根文件系统容器运行；route和expansion都抛出442，
同一个Actor随后完成距离和时间扩展，返回5/6条轨迹及completed-v1标记。
镜像清单摘要 `sha256:0cbfd2a92e3f743c0e016059a767e0af5d5ef9e897864ed8d5d7cbf22e856df8`，
本次产物为Linux arm64；wheel SHA-256为
`05b736a92521a64eed978f5b70177719126dc136ca32b30b593e4ec7de118dd5`。
目标服务器若为amd64，必须单独构建，不将当前arm64产物视为跨架构可用。
