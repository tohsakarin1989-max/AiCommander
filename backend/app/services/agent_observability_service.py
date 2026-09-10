"""Agent 统一运行中心的健康、耗时、用量和成本聚合。"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from math import ceil
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models.agent_run import AgentEvent, AgentRun, AgentUsageRecord
from app.models.ai_model import AIModel


SUCCESS_STATUSES = {"completed", "degraded"}
KNOWN_STATUSES = (
    "queued",
    "planning",
    "running",
    "verifying",
    "waiting_approval",
    "completed",
    "degraded",
    "failed",
    "cancelled",
    "expired",
)
SUPPORTED_MODEL_PROVIDERS = {
    "openai",
    "openai-compatible",
    "azure-openai",
    "anthropic",
    "claude",
}


class AgentObservabilityService:
    @staticmethod
    def build_overview(db: Session, *, days: int = 30) -> dict[str, Any]:
        now = datetime.utcnow()
        since = now - timedelta(days=days)
        runs = (
            db.query(AgentRun)
            .filter(AgentRun.created_at >= since, AgentRun.task_type.notin_(['intelligent_query', 'showcase']))
            .order_by(AgentRun.created_at.asc())
            .all()
        )
        run_ids = [run.id for run in runs]
        usage_records = (
            db.query(AgentUsageRecord)
            .filter(AgentUsageRecord.run_id.in_(run_ids))
            .all()
            if run_ids
            else []
        )
        events = (
            db.query(AgentEvent)
            .filter(AgentEvent.run_id.in_(run_ids))
            .all()
            if run_ids
            else []
        )

        status_counts = {status: 0 for status in KNOWN_STATUSES}
        durations = []
        for run in runs:
            status_counts[run.status] = status_counts.get(run.status, 0) + 1
            duration = AgentObservabilityService._run_duration_ms(run)
            if duration is not None:
                durations.append(duration)

        successful_runs = sum(status_counts.get(status, 0) for status in SUCCESS_STATUSES)
        tool_durations = [
            event.duration_ms
            for event in events
            if event.actor_type == "tool" and event.duration_ms is not None
        ]
        total_tokens = sum(item.total_tokens or 0 for item in usage_records)
        estimated_cost_microusd = sum(
            item.estimated_cost_microusd or 0 for item in usage_records
        )
        provider_rows = AgentObservabilityService._provider_breakdown(runs, usage_records)
        model_catalog = AgentObservabilityService._model_catalog(db)

        return {
            "window_days": days,
            "generated_at": now.isoformat(),
            "summary": {
                "runs_total": len(runs),
                "completed_runs": status_counts["completed"],
                "degraded_runs": status_counts["degraded"],
                "failed_runs": status_counts["failed"],
                "active_runs": sum(
                    status_counts[status]
                    for status in ("queued", "planning", "running", "verifying", "waiting_approval")
                ),
                "completion_rate_percent": round(
                    successful_runs / len(runs) * 100,
                    1,
                ) if runs else 0.0,
                "average_duration_ms": round(sum(durations) / len(durations)) if durations else 0,
                "p95_duration_ms": AgentObservabilityService._percentile_95(durations),
                "tool_calls": len(tool_durations),
                "average_tool_duration_ms": round(
                    sum(tool_durations) / len(tool_durations)
                ) if tool_durations else 0,
                "model_calls": sum(item.request_count or 0 for item in usage_records),
                "total_tokens": total_tokens,
                "estimated_cost_usd": round(estimated_cost_microusd / 1_000_000, 6),
            },
            "status_counts": status_counts,
            "providers": provider_rows,
            "daily": AgentObservabilityService._daily_breakdown(runs, usage_records),
            "runtime": AgentObservabilityService._runtime_status(model_catalog),
            "model_catalog": model_catalog,
        }

    @staticmethod
    def summarize_run(run: AgentRun) -> dict[str, Any]:
        duration = AgentObservabilityService._run_duration_ms(run)
        tool_durations = [
            event.duration_ms or 0
            for event in run.events
            if event.actor_type == "tool" and event.duration_ms is not None
        ]
        usages = list(run.usage_records or [])
        return {
            "duration_ms": duration,
            "tool_duration_ms": sum(tool_durations),
            "model_duration_ms": sum(item.duration_ms or 0 for item in usages),
            "model_calls": sum(item.request_count or 0 for item in usages),
            "input_tokens": sum(item.input_tokens or 0 for item in usages),
            "output_tokens": sum(item.output_tokens or 0 for item in usages),
            "total_tokens": sum(item.total_tokens or 0 for item in usages),
            "estimated_cost_usd": round(
                sum(item.estimated_cost_microusd or 0 for item in usages) / 1_000_000,
                6,
            ),
        }

    @staticmethod
    def usage_payload(usage: AgentUsageRecord) -> dict[str, Any]:
        return {
            "id": usage.id,
            "run_id": usage.run_id,
            "provider": usage.provider,
            "model_name": usage.model_name,
            "status": usage.status,
            "request_count": usage.request_count,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
            "duration_ms": usage.duration_ms,
            "estimated_cost_usd": round(
                (usage.estimated_cost_microusd or 0) / 1_000_000,
                6,
            ),
            "error_code": usage.error_code,
            "created_at": usage.created_at.isoformat() if usage.created_at else None,
        }

    @staticmethod
    def _run_duration_ms(run: AgentRun) -> int | None:
        if run.started_at is None or run.completed_at is None:
            return None
        return max(0, round((run.completed_at - run.started_at).total_seconds() * 1000))

    @staticmethod
    def _percentile_95(values: list[int]) -> int:
        if not values:
            return 0
        ordered = sorted(values)
        return ordered[max(0, ceil(len(ordered) * 0.95) - 1)]

    @staticmethod
    def _provider_breakdown(
        runs: list[AgentRun],
        usage_records: list[AgentUsageRecord],
    ) -> list[dict[str, Any]]:
        buckets: dict[str, dict[str, Any]] = {}
        for run in runs:
            provider = run.model_provider or "deterministic"
            bucket = buckets.setdefault(provider, {
                "provider": provider,
                "runs": 0,
                "completed_runs": 0,
                "degraded_runs": 0,
                "failed_runs": 0,
                "model_calls": 0,
                "total_tokens": 0,
                "estimated_cost_microusd": 0,
                "model_latency_values": [],
                "models": set(),
            })
            bucket["runs"] += 1
            if run.status == "completed":
                bucket["completed_runs"] += 1
            elif run.status == "degraded":
                bucket["degraded_runs"] += 1
            elif run.status == "failed":
                bucket["failed_runs"] += 1
            if run.model_name:
                bucket["models"].add(run.model_name)

        for usage in usage_records:
            bucket = buckets.setdefault(usage.provider, {
                "provider": usage.provider,
                "runs": 0,
                "completed_runs": 0,
                "degraded_runs": 0,
                "failed_runs": 0,
                "model_calls": 0,
                "total_tokens": 0,
                "estimated_cost_microusd": 0,
                "model_latency_values": [],
                "models": set(),
            })
            bucket["model_calls"] += usage.request_count or 0
            bucket["total_tokens"] += usage.total_tokens or 0
            bucket["estimated_cost_microusd"] += usage.estimated_cost_microusd or 0
            bucket["model_latency_values"].append(usage.duration_ms or 0)
            if usage.model_name:
                bucket["models"].add(usage.model_name)

        rows = []
        for provider, bucket in buckets.items():
            latencies = bucket.pop("model_latency_values")
            estimated = bucket.pop("estimated_cost_microusd")
            models = bucket.pop("models")
            rows.append({
                **bucket,
                "models": sorted(models),
                "average_model_duration_ms": round(
                    sum(latencies) / len(latencies)
                ) if latencies else 0,
                "estimated_cost_usd": round(estimated / 1_000_000, 6),
            })
        return sorted(rows, key=lambda item: (-item["runs"], item["provider"]))

    @staticmethod
    def _daily_breakdown(
        runs: list[AgentRun],
        usage_records: list[AgentUsageRecord],
    ) -> list[dict[str, Any]]:
        usage_by_run: dict[str, list[AgentUsageRecord]] = defaultdict(list)
        for usage in usage_records:
            usage_by_run[usage.run_id].append(usage)
        daily: dict[str, dict[str, Any]] = {}
        for run in runs:
            date_key = run.created_at.date().isoformat()
            row = daily.setdefault(date_key, {
                "date": date_key,
                "runs": 0,
                "completed_runs": 0,
                "degraded_runs": 0,
                "failed_runs": 0,
                "total_duration_ms": 0,
                "duration_samples": 0,
                "total_tokens": 0,
                "estimated_cost_microusd": 0,
            })
            row["runs"] += 1
            if run.status in SUCCESS_STATUSES:
                row["completed_runs"] += 1
            if run.status == "degraded":
                row["degraded_runs"] += 1
            if run.status == "failed":
                row["failed_runs"] += 1
            duration = AgentObservabilityService._run_duration_ms(run)
            if duration is not None:
                row["total_duration_ms"] += duration
                row["duration_samples"] += 1
            for usage in usage_by_run.get(run.id, []):
                row["total_tokens"] += usage.total_tokens or 0
                row["estimated_cost_microusd"] += usage.estimated_cost_microusd or 0

        rows = []
        for date_key in sorted(daily):
            row = daily[date_key]
            rows.append({
                "date": date_key,
                "runs": row["runs"],
                "completed_runs": row["completed_runs"],
                "degraded_runs": row["degraded_runs"],
                "failed_runs": row["failed_runs"],
                "average_duration_ms": round(
                    row["total_duration_ms"] / row["duration_samples"]
                ) if row["duration_samples"] else 0,
                "total_tokens": row["total_tokens"],
                "estimated_cost_usd": round(
                    row["estimated_cost_microusd"] / 1_000_000,
                    6,
                ),
            })
        return rows

    @staticmethod
    def _model_catalog(db: Session) -> list[dict[str, Any]]:
        models = (
            db.query(AIModel)
            .filter(AIModel.is_active.is_(True))
            .order_by(AIModel.id.asc())
            .all()
        )
        return [
            {
                "id": model.id,
                "name": model.name,
                "provider": model.provider,
                "model_name": model.model_name,
                "role": model.role,
                "is_default": bool(model.is_default),
            }
            for model in models
            if str(model.provider or "").strip().lower() in SUPPORTED_MODEL_PROVIDERS
        ]

    @staticmethod
    def _runtime_status(model_catalog: list[dict[str, Any]]) -> dict[str, Any]:
        selected_model = next(
            (
                item
                for item in model_catalog
                if item["id"] == settings.AGENT_MODEL_ID
            ),
            None,
        )
        return {
            "deterministic_available": True,
            "external_model_enabled": settings.AGENT_USE_EXTERNAL_MODEL,
            "configured_provider": settings.AGENT_PROVIDER,
            "configured_model": (
                selected_model["model_name"]
                if selected_model
                else settings.AGENT_MODEL or None
            ),
            "configured_model_id": settings.AGENT_MODEL_ID,
            "model_configuration_ready": (
                not settings.AGENT_USE_EXTERNAL_MODEL
                or settings.AGENT_PROVIDER == "openai_agents" and bool(settings.AGENT_MODEL)
                or settings.AGENT_PROVIDER == "model_registry" and selected_model is not None
            ),
            "supported_adapters": ["deterministic", "openai_agents", "model_registry"],
        }
