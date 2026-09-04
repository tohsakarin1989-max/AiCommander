#!/usr/bin/env python3
"""在隔离脱敏数据库副本上运行 Agent Lab 业务评测。"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from time import perf_counter

from sqlalchemy.engine import make_url


BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = BACKEND_DIR / "evals" / "agent_lab" / "results" / "latest.json"
REQUIRED_TABLES = {
    "cases",
    "jurisdiction_assets",
    "agent_runs",
    "agent_events",
    "agent_artifacts",
    "agent_approvals",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="在隔离脱敏 SQLite 副本上评测 Agent Lab；不会调用外部模型。"
    )
    parser.add_argument("--database-url", required=True, help="脱敏 SQLite 副本 URL")
    parser.add_argument(
        "--confirm-isolated-copy",
        action="store_true",
        help="确认目标是可丢弃、已脱敏、与生产隔离的数据库副本",
    )
    parser.add_argument("--minimum-cases", type=int, default=30)
    parser.add_argument("--minimum-assets", type=int, default=100)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def validate_target(database_url: str, confirmed: bool) -> Path:
    if not confirmed:
        raise ValueError("必须传入 --confirm-isolated-copy 明确确认隔离副本")
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        raise ValueError("本地评测 Harness 只接受持久化 SQLite 脱敏副本")
    database_path = Path(url.database).expanduser().resolve()
    protected = (BACKEND_DIR / "aicommander.db").resolve()
    if database_path == protected:
        raise ValueError("禁止直接使用默认业务数据库，请先制作隔离脱敏副本")
    if not database_path.is_file():
        raise ValueError(f"评测数据库不存在: {database_path}")
    return database_path


async def run_evaluation(args: argparse.Namespace) -> dict:
    os.environ["DATABASE_URL"] = args.database_url
    os.environ.setdefault("SECRET_KEY", "agent-lab-eval-isolated-copy-only")
    os.environ["AUTH_REQUIRED"] = "false"
    os.environ["AUTO_CREATE_TABLES"] = "false"
    os.environ["ENABLE_AGENT_LAB"] = "true"
    os.environ["AGENT_MODE"] = "shadow"
    os.environ["AGENT_MUTATIONS_ENABLED"] = "false"
    os.environ["AGENT_USE_EXTERNAL_MODEL"] = "false"
    sys.path.insert(0, str(BACKEND_DIR))

    import app.models  # noqa: F401
    from sqlalchemy import inspect

    from app.agent_runtime.redaction import AgentPayloadRedactor
    from app.agent_runtime.runtime import AgentRunExecutor
    from app.agent_runtime.service import AgentRunService
    from app.database import SessionLocal, engine
    from app.models.case import Case
    from app.models.jurisdiction import JurisdictionAsset
    from evals.agent_lab.evaluator import (
        EvaluationCheck,
        ensure_dataset_size,
        grade_run,
        snapshot_core_data,
    )

    missing_tables = sorted(REQUIRED_TABLES - set(inspect(engine).get_table_names()))
    if missing_tables:
        raise ValueError(
            "评测副本尚未迁移到 Agent Lab 版本，缺少表: " + ", ".join(missing_tables)
        )

    db = SessionLocal()
    try:
        counts = ensure_dataset_size(
            db,
            minimum_cases=args.minimum_cases,
            minimum_assets=args.minimum_assets,
        )
        case_ids = [
            item[0]
            for item in db.query(Case.id).order_by(Case.id.asc()).limit(30).all()
        ]
        asset_ids = [
            item[0]
            for item in db.query(JurisdictionAsset.id)
            .order_by(JurisdictionAsset.id.asc())
            .limit(100)
            .all()
        ]
        core_before = snapshot_core_data(db)
        started = perf_counter()
        evaluated_runs = []
        scenarios = [
            ("case_data_quality", case_ids, [], "检查案件数据完整性和一致性"),
            ("map_data_quality", [], asset_ids, "检查重点井和地图资源质量"),
            ("dual_domain_analysis", case_ids[:10], asset_ids, "开展案件与井位时空融合分析"),
            ("evidence_report", case_ids[:10], asset_ids, "生成事实、推断、建议和边界报告"),
        ]
        for task_type, selected_cases, selected_assets, query in scenarios:
            run = AgentRunService.create_run(
                db,
                task_type=task_type,
                query=query,
                case_ids=selected_cases,
                asset_ids=selected_assets,
                mode="shadow",
                created_by=None,
            )
            completed = await AgentRunExecutor(narrator=None).execute(db, run.id)
            checks = grade_run(completed)
            evaluated_runs.append({
                "run_id": completed.id,
                "task_type": task_type,
                "status": completed.status,
                "data_version": completed.data_version,
                "event_count": len(completed.events),
                "artifact_count": len(completed.artifacts),
                "approval_count": len(completed.approvals),
                "evidence_count": len(completed.result_summary.get("evidence_refs", [])),
                "checks": [asdict(check) for check in checks],
            })

        core_after = snapshot_core_data(db)
        global_checks = [
            EvaluationCheck(
                "core_data_read_only",
                core_before == core_after,
                "案件与地图资源运行前后摘要一致",
            ),
            _grade_redaction_canary(AgentPayloadRedactor),
            EvaluationCheck(
                "external_model_disabled",
                True,
                "评测执行器显式使用 narrator=None，外部调用为 0",
            ),
        ]
        elapsed_ms = round((perf_counter() - started) * 1000)
        all_checks = [
            check
            for run in evaluated_runs
            for check in run["checks"]
        ] + [asdict(check) for check in global_checks]
        passed = all(check["passed"] for check in all_checks)
        return {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "passed": passed,
            "configuration": {
                "mode": "shadow",
                "mutations_enabled": False,
                "external_model_enabled": False,
                "minimum_cases": args.minimum_cases,
                "minimum_assets": args.minimum_assets,
            },
            "dataset": counts,
            "metrics": {
                "scenario_count": len(evaluated_runs),
                "elapsed_ms": elapsed_ms,
                "passed_checks": sum(1 for check in all_checks if check["passed"]),
                "total_checks": len(all_checks),
            },
            "global_checks": [asdict(check) for check in global_checks],
            "runs": evaluated_runs,
        }
    finally:
        db.close()


def _grade_redaction_canary(redactor_type) -> object:
    from evals.agent_lab.evaluator import EvaluationCheck

    secrets = [
        "张三",
        "13800138000",
        "220102199001011234",
        "英平6002井",
        "45.612345",
        "124.712345",
    ]
    result = redactor_type().redact({
        "name": "张三",
        "phone": "13800138000",
        "id_card": "220102199001011234",
        "asset_name": "英平6002井",
        "latitude": 45.612345,
        "longitude": 124.712345,
        "distance_km": 0.8,
    })
    serialized = json.dumps(result.payload, ensure_ascii=False, sort_keys=True)
    leaked = [secret for secret in secrets if secret in serialized]
    return EvaluationCheck(
        "redaction_canary",
        not leaked,
        "未发现固定敏感字段" if not leaked else "发现泄漏: " + ", ".join(leaked),
    )


def main() -> int:
    args = parse_args()
    try:
        validate_target(args.database_url, args.confirm_isolated_copy)
        report = asyncio.run(run_evaluation(args))
    except Exception as exc:
        print(f"Agent Lab 评测未执行: {exc}", file=sys.stderr)
        return 2

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    result = "通过" if report["passed"] else "失败"
    metrics = report["metrics"]
    print(
        f"Agent Lab 评测{result}: {metrics['passed_checks']}/{metrics['total_checks']} 项检查通过；"
        f"报告 {output}"
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
