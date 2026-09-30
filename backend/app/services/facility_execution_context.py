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
    valid_at: datetime
    known_at: datetime
    policy_version: str
    purpose: str = "facility_reference"
    road_permission: str = "resolve_separately_from_current_grants"
    schema_version: str = "facility-context-6.2-1"

    def public(self):
        data = asdict(self)
        data["valid_at"] = self.valid_at.isoformat()
        data["known_at"] = self.known_at.isoformat()
        return data


def freeze_facility_context(db, *, area_id=None, valid_at=None, known_at=None):
    user = _identity(db)
    allowed = db.info["authorized_area_ids"]
    if area_id is not None:
        if allowed is not None and area_id not in allowed:
            raise PermissionError("facility_scope_denied")
        if db.query(OperationalArea.id).filter_by(id=area_id, status="active").first() is None:
            raise ValueError("facility_area_unavailable")
    now = datetime.now(timezone.utc)
    known = utc_datetime(known_at) or now
    if known > now:
        raise ValueError("future_knowledge_is_not_available")
    revision = db.query(QueryScopeRevision.revision).filter_by(id=1).scalar()
    policy = result_hash({"schema": "facility-scope-6.2-1", "user": user.id,
        "role": user.role, "session_version": user.session_version,
        "areas": allowed, "area_access": db.info.get("area_access_levels"),
        "revision": revision})
    return FacilityExecutionContext(user.id, user.role, area_id,
        tuple(allowed) if allowed is not None else None,
        utc_datetime(valid_at) or now, known, policy)
