# Agent Lab 本地业务评测

该 Harness 只在隔离、可丢弃、已脱敏且已完成 Alembic 迁移的 SQLite 数据库副本上运行。
它不会调用外部模型，也不会批准候选操作。默认门槛为至少 30 个案件和 100 个地图资源。

```bash
cd backend
venv/bin/python evals/agent_lab/run_local.py \
  --database-url sqlite:////绝对路径/aicommander-agent-eval.db \
  --confirm-isolated-copy
```

结果写入 `evals/agent_lab/results/latest.json`，任一轨迹、证据、边界、只读或脱敏检查失败时退出码为 1；
数据不足、目标不是持久化 SQLite、直接指向默认业务库或迁移缺失时退出码为 2。

这套业务评测不替代单元测试、部署恢复演练和人工复核。竞赛冻结前应保存五次独立执行报告，
并在报告外记录人工处理时长、Agent 辅助时长和人工采纳率。
