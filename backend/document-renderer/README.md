# 冻结成果文件渲染器（v4.1开发中）

输入为`case-result-document-4.1.0-1`内容块JSON，标准输入读取，标准输出为DOCX二进制。
不接受文件路径、外部地址或命令，不执行输入中的HTML。只负责排版，调用方仍必须通过
`load_case_result_document`重新校验权限；本目录的命令不是对外接口。

联网构建区运行`npm ci --ignore-scripts`，依赖由package-lock.json固定。部署前需将Node、依赖及
允许分发的中文字体随镜像/离线包提供，不能在内网请求时联网安装。当前实际验证Node 24.19.0
及docx 9.6.1；后端镜像、调用服务和健康检查尚未接入，不能标为可部署的导出能力。

DOCX指定Arial与Noto Sans CJK SC；字体名称不等于嵌入字体，使用方Word及服务端排版引擎须有可用中文字体。
含地图版本或候选的输入暂以`frozen_map_renderer_required`拒绝，不能静默丢弃地图。
后续需要接通冻结地图图像、来源/复杂结构化数据的可读表格、长文分页、权限下载和PDF。

真实依赖测试：在安装上述依赖后，运行`backend/venv/bin/python -m pytest backend/tests/test_case_result_docx.py -q`。
测试机可显式配置`AIC_TEST_DOCX_NODE`与`NODE_PATH`使用已有依赖；缺依赖跳过不代表门禁通过。

2026-09-11：渲染器4项及内容层5项共9项通过（0.87秒）。真实DOCX经LibreOffice打开转换并查看单页截图，
中文、两行原文、HTML作为纯文本、表头、引用和页码正常。首次字体发现失败造成缺字，使用临时
fontconfig指向本机字体后复验通过；这不是生产Linux字体包验收，也未重新分发系统字体。
首次Node 26额外警告影响错误断言，Node 24通过；测试现核对stderr最后错误行，仍要求退出失败且stdout为空。
仅验证短合成样本，未验证跨页长文、真实地图和完整业务导出，不交付临时PDF为正式报告。
