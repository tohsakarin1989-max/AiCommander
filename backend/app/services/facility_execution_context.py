"""Typed read context. Visibility is not permission to traverse a road."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from app.models.map_foundation import OperationalArea
from app.models.query_scope_revision import QueryScopeRevision
from app.services.intelligent_query_context import result_hash
from app.services.intelligent_query_tasks import _identity
from app.utils.datetimes import utc_datetime


@dataclass(frozen=True)
class FacilityExecutionContext:
    user_id: int
    role: str
    operational_area_id: int | None
    authorized_area_ids: tuple[int, ...] | None
    valid_at: datetime | None
    known_at: datetime
    policy_version: str
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    knowledge_mode: str = "retrospective"
    purpose: str = "facility_reference"
    road_permission: str = "resolve_separately_from_current_grants"
    schema_version: str = "facility-context-6.2-1"

    def public(self):
        data = asdict(self)
        data["valid_at"] = self.valid_at.isoformat() if self.valid_at else None
        data["valid_from"] = self.valid_from.isoformat() if self.valid_from else None
        data["valid_to"] = self.valid_to.isoformat() if self.valid_to else None
        data["known_at"] = self.known_at.isoformat()
        return data


def freeze_facility_context(db, *, area_id=None, valid_at=None, known_at=None,
                            valid_from=None, valid_to=None, knowledge_mode=None):
    from app.services.facility_temporal_conditions import knowledge_context, time_window
    from app.services.facility_identity_service import _utc
    user = _identity(db)
    allowed = db.info["authorized_area_ids"]
    if area_id is not None:
        if allowed is not None and area_id not in allowed:
            raise PermissionError("facility_scope_denied")
        if db.query(OperationalArea.id).filter_by(id=area_id, status="active").first() is None:
            raise ValueError("facility_area_unavailable")
    now = datetime.now(timezone.utc)
    mode, known = knowledge_context(known_at=known_at, knowledge_mode=knowledge_mode)
    if valid_at is None and valid_from is None and valid_to is None:
        valid_at = now  # An unfiltered facility view is current, not an unknown-time case.
    window = time_window(valid_at=valid_at, valid_from=valid_from, valid_to=valid_to)
    revision = db.query(QueryScopeRevision.revision).filter_by(id=1).scalar()
    policy = result_hash({"schema": "facility-scope-6.2-1", "user": user.id,
        "role": user.role, "session_version": user.session_version,
        "areas": allowed, "area_access": db.info.get("area_access_levels"),
        "revision": revision})
    return FacilityExecutionContext(user.id, user.role, area_id,
        tuple(allowed) if allowed is not None else None,
        _utc(window["valid_at"]), known, policy,
        _utc(window["valid_from"]), _utc(window["valid_to"]), mode)
