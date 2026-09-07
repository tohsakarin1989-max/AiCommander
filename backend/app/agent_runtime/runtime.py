"""可恢复、可审计的 Agent 运行执行器。"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from time import perf_counter
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from app.agent_runtime.providers import AgentNarrationOutcome, AgentNarrator, build_narrator
from app.agent_runtime.redaction import AgentPayloadRedactor
from app.agent_runtime.service import AgentRunService
from app.agent_runtime.tools import AgentToolContext, AgentToolRegistry
from app.config import settings
from app.models.agent_run import AgentApproval, AgentArtifact, AgentRun


_AUTO_NARRATOR = object()


TASK_TO_TOOLS = {
    "case_data_quality": ["case_data_quality"],
    "map_data_quality": ["map_data_quality"],
    "dual_domain_analysis": ["dual_domain_analysis"],
    "evidence_report": ["case_data_quality", "map_data_quality", "dual_domain_analysis"],
}

EXTERNAL_TASK_GOALS = {
    "case_data_quality": "整理案件数据质量事实、缺口和人工补录建议",
    "map_data_quality": "整理地图资产质量事实、待核验问题和候选修正依据",
    "dual_domain_analysis": "整理案件与生产目标的时空条件、信息缺口和防控参考",
    "evidence_report": "形成区分事实、推断、建议和边界的综合证据报告",
}


class AgentRunExecutor:
    def __init__(
        self,
        *,
        narrator: Optional[AgentNarrator] | object = _AUTO_NARRATOR,
        tool_registry: Optional[AgentToolRegistry] = None,
    ) -> None:
        self._auto_narrator = narrator is _AUTO_NARRATOR
        self.narrator = build_narrator() if self._auto_narrator else narrator
        self.tool_registry = tool_registry or AgentToolRegistry()

    async def execute(self, db: Session, run_id: str) -> AgentRun:
        run = AgentRunService.get_run(db, run_id)
        if run.status == "cancelled":
            return run
        if run.status in {"completed", "degraded", "expired", "waiting_approval"}:
            return run
        if run.task_type not in TASK_TO_TOOLS:
            return self._fail(db, run, "unsupported_task_type")

        run.status = "planning"
        run.error_message = None
        run.completed_at = None
        run.started_at = run.started_at or datetime.utcnow()
        run.attempt_count = (run.attempt_count or 0) + 1
        AgentRunService.append_event(
            db,
            run,
            event_type="planning_started",
            status="planning",
            output_summary={"tools": TASK_TO_TOOLS[run.task_type]},
        )
        db.commit()

        try:
            run.status = "running"
            AgentRunService.append_event(
                db,
                run,
                event_type="run_started",
                status="running",
            )
            db.commit()

            context = AgentToolContext(
                case_ids=list(run.case_ids or []),
                asset_ids=list(run.asset_ids or []),
                query=run.query,
            )
            tool_outputs: list[dict[str, Any]] = []
            for tool_name in TASK_TO_TOOLS[run.task_type][: settings.AGENT_MAX_STEPS]:
                db.refresh(run)
                if run.status == "cancelled":
                    return AgentRunService.get_run(db, run.id)
                started = perf_counter()
                output = self.tool_registry.execute(tool_name, db, context)
                duration_ms = round((perf_counter() - started) * 1000)
                tool_outputs.append(output)
                AgentRunService.append_event(
                    db,
                    run,
                    event_type="tool_completed",
                    status="running",
                    actor_type="tool",
                    actor_name=tool_name,
                    input_summary={
                        "case_count": len(context.case_ids),
                        "asset_count": len(context.asset_ids),
                    },
                    output_summary={
                        "fact_count": len(output.get("facts", [])),
                        "finding_count": len(output.get("findings", [])),
                        "candidate_count": len(output.get("candidate_actions", [])),
                    },
                    evidence_refs=output.get("evidence_refs", []),
                    duration_ms=duration_ms,
                )
                db.commit()

            db.refresh(run)
            if run.status == "cancelled":
                return AgentRunService.get_run(db, run.id)

            run.status = "verifying"
            AgentRunService.append_event(
                db,
                run,
                event_type="verification_started",
                status="verifying",
                output_summary={"tool_count": len(tool_outputs)},
                evidence_refs=list(dict.fromkeys(
                    str(ref)
                    for output in tool_outputs
                    for ref in output.get("evidence_refs", [])
                )),
            )
            db.commit()

            combined = self._combine(tool_outputs)
            source_signature = hashlib.sha256(
                json.dumps(tool_outputs, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            artifact = AgentArtifact(
                id=str(uuid4()),
                run_id=run.id,
                artifact_type="analysis_report",
                version=run.attempt_count,
                content=combined,
                evidence_refs=combined["evidence_refs"],
                source_signature=source_signature,
            )
            db.add(artifact)
            db.flush()
            # 影子模式保留候选轨迹用于离线评测；受控辅助模式中只有独立的
            # 地图数据管家可以进入审批，综合报告和双域研判始终只读。
            if run.task_type == "map_data_quality" or run.mode != "assist":
                self._stage_approvals(db, run, artifact, tool_outputs)

            degraded = False
            narrator = self.narrator
            narrator_resolution_error: Exception | None = None
            if (
                self._auto_narrator
                and narrator is None
                and settings.AGENT_USE_EXTERNAL_MODEL
                and settings.AGENT_PROVIDER == "model_registry"
            ):
                try:
                    narrator = build_narrator(db)
                except Exception as exc:
                    narrator_resolution_error = exc

            if narrator_resolution_error is not None:
                degraded = True
                run.model_provider = settings.AGENT_PROVIDER
                run.model_name = f"configured-model-{settings.AGENT_MODEL_ID or 'unknown'}"
                AgentRunService.record_usage(
                    db,
                    run,
                    provider=run.model_provider,
                    model_name=run.model_name,
                    status="failed",
                    error_code=type(narrator_resolution_error).__name__,
                )
                AgentRunService.append_event(
                    db,
                    run,
                    event_type="model_degraded",
                    status="degraded",
                    actor_type="model",
                    actor_name=settings.AGENT_PROVIDER,
                    error_message=type(narrator_resolution_error).__name__,
                    output_summary={"fallback": "deterministic"},
                )
            elif narrator is not None:
                external = AgentPayloadRedactor().redact({
                    "task_type": run.task_type,
                    "tool_outputs": tool_outputs,
                })
                run.model_provider = narrator.provider_name
                run.model_name = narrator.model_name
                model_started = perf_counter()
                try:
                    raw_outcome = await narrator.summarize(
                        EXTERNAL_TASK_GOALS[run.task_type],
                        external.payload,
                    )
                    if isinstance(raw_outcome, AgentNarrationOutcome):
                        narrative = raw_outcome.content
                        usage = raw_outcome.usage
                    else:
                        narrative = raw_outcome
                        usage = None
                    model_duration_ms = round((perf_counter() - model_started) * 1000)
                    input_tokens = usage.input_tokens if usage else 0
                    output_tokens = usage.output_tokens if usage else 0
                    request_count = usage.request_count if usage else 0
                    estimated_cost_microusd = self._estimated_cost_microusd(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        input_price=getattr(narrator, "input_cost_per_million_usd", 0),
                        output_price=getattr(narrator, "output_cost_per_million_usd", 0),
                    )
                    combined = self._merge_narrative(combined, narrative)
                    artifact.content = combined
                    AgentRunService.record_usage(
                        db,
                        run,
                        provider=narrator.provider_name,
                        model_name=narrator.model_name,
                        status="completed",
                        request_count=request_count,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        duration_ms=model_duration_ms,
                        estimated_cost_microusd=estimated_cost_microusd,
                    )
                    AgentRunService.append_event(
                        db,
                        run,
                        event_type="model_completed",
                        status="verifying",
                        actor_type="model",
                        actor_name=narrator.provider_name,
                        output_summary={
                            "external_policy": settings.AGENT_EXTERNAL_DATA_POLICY,
                            "request_count": request_count,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "total_tokens": input_tokens + output_tokens,
                            "estimated_cost_usd": round(
                                estimated_cost_microusd / 1_000_000,
                                6,
                            ),
                        },
                        evidence_refs=combined["evidence_refs"],
                        duration_ms=model_duration_ms,
                    )
                except Exception as exc:
                    degraded = True
                    model_duration_ms = round((perf_counter() - model_started) * 1000)
                    AgentRunService.record_usage(
                        db,
                        run,
                        provider=narrator.provider_name,
                        model_name=narrator.model_name,
                        status="failed",
                        request_count=1,
                        duration_ms=model_duration_ms,
                        error_code=type(exc).__name__,
                    )
                    AgentRunService.append_event(
                        db,
                        run,
                        event_type="model_degraded",
                        status="degraded",
                        actor_type="model",
                        actor_name=narrator.provider_name,
                        error_message=type(exc).__name__,
                        output_summary={"fallback": "deterministic"},
                        duration_ms=model_duration_ms,
                    )

            db.refresh(run)
            if run.status == "cancelled":
                # 管理员停用或用户取消优先于迟到的模型结果；丢弃本事务中尚未
                # 提交的成果物和模型事件，保留取消事件作为最终状态。
                db.rollback()
                return AgentRunService.get_run(db, run.id)

            pending_approvals = db.query(AgentApproval).filter(
                AgentApproval.run_id == run.id,
                AgentApproval.status == "pending",
            ).count()
            if degraded:
                run.status = "degraded"
            elif run.mode == "assist" and pending_approvals:
                run.status = "waiting_approval"
            else:
                run.status = "completed"
            run.completed_at = datetime.utcnow() if run.status != "waiting_approval" else None
            execution_mode = "agent_lab"
            if degraded:
                execution_mode = "deterministic_fallback"
            elif narrator is None:
                execution_mode = "deterministic"
            run.result_summary = {
                **combined,
                "mode": execution_mode,
                "pending_approval_count": pending_approvals,
            }
            AgentRunService.append_event(
                db,
                run,
                event_type="approval_required" if run.status == "waiting_approval" else "run_completed",
                status=run.status,
                output_summary={
                    "artifact_id": artifact.id,
                    "pending_approval_count": pending_approvals,
                    "degraded": degraded,
                },
                evidence_refs=combined["evidence_refs"],
            )
            db.commit()
            return AgentRunService.get_run(db, run.id)
        except Exception as exc:
            db.rollback()
            run = AgentRunService.get_run(db, run_id)
            return self._fail(db, run, type(exc).__name__)

    @staticmethod
    def _stage_approvals(
        db: Session,
        run: AgentRun,
        artifact: AgentArtifact,
        tool_outputs: list[dict[str, Any]],
    ) -> None:
        for output in tool_outputs:
            for action in output.get("candidate_actions", []):
                idempotency_source = {
                    "run_id": run.id,
                    "action_type": action["action_type"],
                    "target_type": action["target_type"],
                    "target_id": action["target_id"],
                    "patch": action["patch"],
                }
                idempotency_key = hashlib.sha256(
                    json.dumps(idempotency_source, ensure_ascii=False, sort_keys=True).encode("utf-8")
                ).hexdigest()
                db.add(AgentApproval(
                    id=str(uuid4()),
                    run_id=run.id,
                    artifact_id=artifact.id,
                    action_type=action["action_type"],
                    target_type=action["target_type"],
                    target_id=action["target_id"],
                    candidate_patch=action["patch"],
                    source_signature=action["source_signature"],
                    status="pending",
                    requested_by=run.created_by,
                    idempotency_key=idempotency_key,
                    execution_result={},
                    expires_at=datetime.utcnow() + timedelta(hours=settings.AGENT_APPROVAL_TTL_HOURS),
                ))
        db.flush()

    @staticmethod
    def _combine(tool_outputs: list[dict[str, Any]]) -> dict[str, Any]:
        def collect(key: str) -> list[Any]:
            return [item for output in tool_outputs for item in output.get(key, [])]

        evidence_refs = list(dict.fromkeys(str(item) for item in collect("evidence_refs")))
        facts = collect("facts")
        findings = collect("findings")
        inferences = list(dict.fromkeys(str(item) for item in collect("inferences") if item))
        recommendations = list(dict.fromkeys(str(item) for item in collect("recommendations") if item))
        information_gaps = list(dict.fromkeys(str(item) for item in collect("information_gaps") if item))
        boundary = list(dict.fromkeys(str(item) for item in collect("boundary") if item))
        case_asset_links = collect("case_asset_links")
        hotspots = collect("hotspots")
        result = (
            f"已完成 {len(tool_outputs)} 项只读分析，形成 {len(facts)} 条事实记录、"
            f"{len(findings)} 个数据问题和 {len(evidence_refs)} 条证据引用。"
        )
        return {
            "result": result,
            "steps": [output.get("tool") for output in tool_outputs],
            "facts": facts,
            "findings": findings,
            "inferences": inferences,
            "recommendations": recommendations,
            "information_gaps": information_gaps,
            "evidence_refs": evidence_refs,
            "boundary": boundary,
            "case_asset_links": case_asset_links,
            "hotspots": hotspots,
            "confidence": AgentRunExecutor._confidence(facts, evidence_refs, information_gaps),
        }

    @staticmethod
    def _merge_narrative(base: dict[str, Any], narrative: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        if narrative.get("result"):
            merged["result"] = str(narrative["result"])
        for key in ("inferences", "recommendations", "information_gaps", "boundary"):
            merged[key] = list(dict.fromkeys([
                *[str(item) for item in base.get(key, []) if item],
                *[str(item) for item in narrative.get(key, []) if item],
            ]))
        return merged

    @staticmethod
    def _confidence(facts: list[Any], evidence_refs: list[str], gaps: list[str]) -> float:
        if not facts or not evidence_refs:
            return 0.2
        penalty = min(len(gaps) * 0.03, 0.3)
        return round(max(0.35, min(0.9, 0.55 + len(evidence_refs) * 0.03 - penalty)), 2)

    @staticmethod
    def _estimated_cost_microusd(
        *,
        input_tokens: int,
        output_tokens: int,
        input_price: float,
        output_price: float,
    ) -> int:
        # 美元/百万 token 转换成微美元后，数值等于 token 数乘以对应单价。
        return max(0, round(
            max(0, input_tokens) * max(0.0, input_price)
            + max(0, output_tokens) * max(0.0, output_price)
        ))

    @staticmethod
    def _fail(db: Session, run: AgentRun, reason: str) -> AgentRun:
        run.status = "failed"
        run.error_message = reason
        run.completed_at = datetime.utcnow()
        AgentRunService.append_event(
            db,
            run,
            event_type="run_failed",
            status="failed",
            error_message=reason,
        )
        db.commit()
        return AgentRunService.get_run(db, run.id)
