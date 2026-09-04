"""可恢复、可审计的 Agent 运行执行器。"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from time import perf_counter
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from app.agent_runtime.providers import AgentNarrator, build_narrator
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
        self.narrator = build_narrator() if narrator is _AUTO_NARRATOR else narrator
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
            self._stage_approvals(db, run, artifact, tool_outputs)

            degraded = False
            if self.narrator is not None:
                external = AgentPayloadRedactor().redact({
                    "task_type": run.task_type,
                    "tool_outputs": tool_outputs,
                })
                try:
                    narrative = await self.narrator.summarize(
                        EXTERNAL_TASK_GOALS[run.task_type],
                        external.payload,
                    )
                    combined = self._merge_narrative(combined, narrative)
                    run.model_provider = self.narrator.provider_name
                    run.model_name = self.narrator.model_name
                    artifact.content = combined
                    AgentRunService.append_event(
                        db,
                        run,
                        event_type="model_completed",
                        status="verifying",
                        actor_type="model",
                        actor_name=self.narrator.provider_name,
                        output_summary={"external_policy": settings.AGENT_EXTERNAL_DATA_POLICY},
                        evidence_refs=combined["evidence_refs"],
                    )
                except Exception as exc:
                    degraded = True
                    AgentRunService.append_event(
                        db,
                        run,
                        event_type="model_degraded",
                        status="degraded",
                        actor_type="model",
                        actor_name=self.narrator.provider_name,
                        error_message=type(exc).__name__,
                        output_summary={"fallback": "deterministic"},
                    )

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
            run.result_summary = {
                **combined,
                "mode": "deterministic_fallback" if degraded or self.narrator is None else "agent_lab",
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
