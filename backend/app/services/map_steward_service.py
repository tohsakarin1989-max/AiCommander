"""地图数据管家试用控制、指定用户和验收指标。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.config import settings
from app.models.agent_run import AgentApproval, AgentArtifact, AgentRun
from app.models.system_config import SystemConfig
from app.models.user import User


@dataclass(frozen=True)
class MapStewardControl:
    enabled: bool
    mutations_suspended: bool
    pilot_user_ids: tuple[int, ...]
    reason: str | None = None
    updated_by: int | None = None
    updated_at: str | None = None


class MapStewardPilotService:
    ENABLED_KEY = "agent_map_pilot_enabled"
    SUSPENDED_KEY = "agent_map_mutations_suspended"
    USERS_KEY = "agent_map_pilot_user_ids"
    CATEGORY = "agent_map_pilot"
    MAX_PILOT_USERS = 50

    @staticmethod
    def _config_value(db: Session, key: str, default: str) -> str:
        config = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
        return config.config_value if config and config.config_value is not None else default

    @staticmethod
    def _parse_ids(value: str) -> tuple[int, ...]:
        try:
            loaded = json.loads(value)
        except (TypeError, ValueError):
            return ()
        if not isinstance(loaded, list):
            return ()
        normalized: list[int] = []
        for item in loaded:
            if isinstance(item, bool):
                continue
            try:
                user_id = int(item)
            except (TypeError, ValueError):
                continue
            if user_id > 0 and user_id not in normalized:
                normalized.append(user_id)
        return tuple(normalized[: MapStewardPilotService.MAX_PILOT_USERS])

    @staticmethod
    def get_control(db: Session) -> MapStewardControl:
        enabled_config = db.query(SystemConfig).filter(
            SystemConfig.config_key == MapStewardPilotService.ENABLED_KEY
        ).first()
        metadata = dict(enabled_config.extra_data or {}) if enabled_config else {}
        enabled_value = enabled_config.config_value if enabled_config else "false"
        return MapStewardControl(
            enabled=str(enabled_value).strip().lower() == "true",
            mutations_suspended=(
                MapStewardPilotService._config_value(
                    db,
                    MapStewardPilotService.SUSPENDED_KEY,
                    "true",
                ).strip().lower()
                != "false"
            ),
            pilot_user_ids=MapStewardPilotService._parse_ids(
                MapStewardPilotService._config_value(
                    db,
                    MapStewardPilotService.USERS_KEY,
                    "[]",
                )
            ),
            reason=str(metadata.get("reason") or "").strip() or None,
            updated_by=int(metadata["updated_by"]) if metadata.get("updated_by") else None,
            updated_at=str(metadata.get("updated_at") or "").strip() or None,
        )

    @staticmethod
    def _upsert(
        db: Session,
        *,
        key: str,
        value: str,
        config_type: str,
        description: str,
        extra_data: dict[str, Any] | None = None,
    ) -> None:
        config = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
        if config is None:
            config = SystemConfig(config_key=key)
            db.add(config)
        config.config_value = value
        config.config_type = config_type
        config.category = MapStewardPilotService.CATEGORY
        config.description = description
        config.is_encrypted = "false"
        if extra_data is not None:
            config.extra_data = extra_data

    @staticmethod
    def set_control(
        db: Session,
        *,
        enabled: bool,
        mutations_suspended: bool,
        pilot_user_ids: Iterable[int],
        updated_by: int | None,
        reason: str,
    ) -> MapStewardControl:
        normalized_ids: list[int] = []
        for item in pilot_user_ids:
            user_id = int(item)
            if user_id > 0 and user_id not in normalized_ids:
                normalized_ids.append(user_id)
        if len(normalized_ids) > MapStewardPilotService.MAX_PILOT_USERS:
            raise ValueError("too_many_pilot_users")
        if enabled and not normalized_ids:
            raise ValueError("pilot_user_required")

        if enabled:
            users = db.query(User).filter(User.id.in_(normalized_ids)).all()
            eligible_ids = {
                user.id
                for user in users
                if user.is_active and user.role in {"admin", "analyst"}
            }
            if set(normalized_ids) != eligible_ids:
                raise ValueError("pilot_user_not_eligible")

        clean_reason = reason.strip()
        changed_at = datetime.now(timezone.utc).isoformat()
        metadata = {
            "reason": clean_reason,
            "updated_by": updated_by,
            "updated_at": changed_at,
        }
        MapStewardPilotService._upsert(
            db,
            key=MapStewardPilotService.ENABLED_KEY,
            value="true" if enabled else "false",
            config_type="boolean",
            description="地图数据管家指定用户试用总开关",
            extra_data=metadata,
        )
        MapStewardPilotService._upsert(
            db,
            key=MapStewardPilotService.SUSPENDED_KEY,
            value="true" if mutations_suspended else "false",
            config_type="boolean",
            description="地图数据管家候选写入暂停开关",
        )
        MapStewardPilotService._upsert(
            db,
            key=MapStewardPilotService.USERS_KEY,
            value=json.dumps(normalized_ids),
            config_type="json",
            description="地图数据管家指定试用用户 ID 列表",
        )
        db.commit()
        return MapStewardPilotService.get_control(db)

    @staticmethod
    def is_pilot_user(control: MapStewardControl, user_id: int | None) -> bool:
        return bool(user_id and user_id in control.pilot_user_ids)

    @staticmethod
    def eligible_users(db: Session) -> list[dict[str, Any]]:
        users = (
            db.query(User)
            .filter(User.is_active.is_(True), User.role.in_(("admin", "analyst")))
            .order_by(User.display_name.asc(), User.id.asc())
            .all()
        )
        return [
            {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "role": user.role,
            }
            for user in users
        ]

    @staticmethod
    def metrics(db: Session) -> dict[str, Any]:
        runs = db.query(AgentRun).filter(
            AgentRun.task_type == "map_data_quality",
            AgentRun.mode == "assist",
        ).all()
        run_ids = [run.id for run in runs]
        artifacts = (
            db.query(AgentArtifact).filter(AgentArtifact.run_id.in_(run_ids)).all()
            if run_ids else []
        )
        approvals = (
            db.query(AgentApproval).filter(AgentApproval.run_id.in_(run_ids)).all()
            if run_ids else []
        )
        evidence_artifacts = sum(1 for item in artifacts if item.evidence_refs)
        decided_count = sum(1 for item in approvals if item.status in {"executed", "rejected"})
        executed_count = sum(1 for item in approvals if item.status == "executed")
        return {
            "runs_total": len(runs),
            "runs_completed": sum(1 for run in runs if run.status in {"completed", "degraded"}),
            "runs_failed": sum(1 for run in runs if run.status == "failed"),
            "candidate_count": len(approvals),
            "pending_approval_count": sum(1 for item in approvals if item.status == "pending"),
            "executed_approval_count": executed_count,
            "rejected_approval_count": sum(1 for item in approvals if item.status == "rejected"),
            "adoption_rate_percent": round(executed_count / decided_count * 100) if decided_count else 0,
            "evidence_coverage_percent": (
                round(evidence_artifacts / len(artifacts) * 100) if artifacts else 0
            ),
        }

    @staticmethod
    def build_status(
        db: Session,
        *,
        principal_user_id: int | None,
        principal_role: str | None,
    ) -> dict[str, Any]:
        control = MapStewardPilotService.get_control(db)
        authorized = MapStewardPilotService.is_pilot_user(control, principal_user_id)
        environment_ready = (
            settings.ENABLE_AGENT_LAB
            and settings.AGENT_MODE == "assist"
        )
        if not control.enabled:
            state = "disabled"
        elif control.mutations_suspended:
            state = "suspended"
        elif not environment_ready or not settings.AGENT_MUTATIONS_ENABLED:
            state = "read_only"
        else:
            state = "ready"
        payload: dict[str, Any] = {
            "state": state,
            "enabled": control.enabled,
            "mutations_suspended": control.mutations_suspended,
            "reason": control.reason,
            "updated_by": control.updated_by,
            "updated_at": control.updated_at,
            "global_mode": settings.AGENT_MODE,
            "environment_ready": environment_ready,
            "current_user_authorized": authorized,
            "can_start": control.enabled and environment_ready and authorized,
            "can_apply_changes": (
                control.enabled
                and not control.mutations_suspended
                and environment_ready
                and settings.AGENT_MUTATIONS_ENABLED
                and authorized
            ),
            "max_assets_per_run": settings.AGENT_MAP_PILOT_MAX_ASSETS,
            "metrics": MapStewardPilotService.metrics(db),
        }
        if principal_role == "admin":
            payload["pilot_user_ids"] = list(control.pilot_user_ids)
            payload["eligible_users"] = MapStewardPilotService.eligible_users(db)
        return payload
