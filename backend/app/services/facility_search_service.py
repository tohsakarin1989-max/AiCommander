"""One bounded facility lookup for ordinary pages and assistant tools.

Old names and source identifiers are search evidence, never inferred identity or
current facts. Source authorization is evaluated in SQL before count/pagination.
No index, model call, or source mutation is performed here.
"""
import json

from sqlalchemy import Boolean, and_, cast, func, or_, select, String
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement

from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import (
    FacilityIdentityDecision, FacilitySourceIdentity, JurisdictionAssetVersion,
    MapFeatureClaim, MapSource,
)


class _VisibleSources(FunctionElement):
    type = Boolean()
    inherit_cache = True


class _VisibleSnapshotSources(_VisibleSources):
    inherit_cache = True


@compiles(_VisibleSources, "sqlite")
@compiles(_VisibleSnapshotSources, "sqlite")
def _sqlite_sources(element, compiler, **kwargs):
    raw, area = (compiler.process(part, **kwargs) for part in element.clauses)
    path = "'$.attributes'" if isinstance(element, _VisibleSnapshotSources) else "'$'"
    kind = f"json_type({raw}, {path})"
    # json_each's primitive values are not necessarily valid JSON documents.
    # Guard each object before invoking JSON functions on its contents.
    attrs = f"CASE WHEN {kind} = 'object' THEN json_extract({raw}, {path}) ELSE '{{}}' END"

    def source_ok(obj):
        typ = f"json_type({obj}, '$.source_id')"
        value = f"json_extract({obj}, '$.source_id')"
        return f"""({typ} IS NULL OR {typ} = 'null' OR
            ({typ} = 'integer' AND EXISTS (SELECT 1 FROM map_sources AS fs_src
             WHERE fs_src.id > 0 AND CAST(fs_src.id AS TEXT) = CAST({value} AS TEXT)
               AND fs_src.status = 'active' AND fs_src.operational_area_id = {area})))"""

    group_kind = f"json_type({attrs}, '$.field_groups')"
    groups = f"CASE WHEN {group_kind} = 'object' THEN json_extract({attrs}, '$.field_groups') ELSE '{{}}' END"
    metadata = "CASE WHEN fs_group.type = 'object' THEN fs_group.value ELSE '{}' END"
    return f"""(({kind} IS NULL OR {kind} IN ('null', 'object'))
      AND {source_ok(attrs)}
      AND ({group_kind} IS NULL OR {group_kind} IN ('null', 'object'))
      AND NOT EXISTS (SELECT 1 FROM json_each({groups}) AS fs_group
        WHERE fs_group.type <> 'object' OR NOT {source_ok(metadata)}))"""


@compiles(_VisibleSources, "postgresql")
@compiles(_VisibleSnapshotSources, "postgresql")
def _postgres_sources(element, compiler, **kwargs):
    raw, area = (compiler.process(part, **kwargs) for part in element.clauses)
    attrs = f"CAST({raw} AS JSONB)"
    if isinstance(element, _VisibleSnapshotSources):
        attrs = f"({attrs} -> 'attributes')"
    kind = f"jsonb_typeof({attrs})"

    def source_ok(obj):
        value = f"({obj} -> 'source_id')"
        return f"""({value} IS NULL OR jsonb_typeof({value}) = 'null' OR
            (jsonb_typeof({value}) = 'number' AND EXISTS
             (SELECT 1 FROM map_sources AS fs_src WHERE fs_src.id > 0
              AND CAST(fs_src.id AS TEXT) = ({obj} ->> 'source_id')
              AND fs_src.status = 'active' AND fs_src.operational_area_id = {area})))"""

    groups = f"({attrs} -> 'field_groups')"
    safe_groups = f"CASE WHEN jsonb_typeof({groups}) = 'object' THEN {groups} ELSE '{{}}'::jsonb END"
    return f"""(({kind} IS NULL OR {kind} IN ('null', 'object'))
      AND {source_ok(attrs)}
      AND (jsonb_typeof({groups}) IS NULL OR jsonb_typeof({groups}) IN ('null', 'object'))
      AND NOT EXISTS (SELECT 1 FROM jsonb_each({safe_groups}) AS fs_group
        WHERE jsonb_typeof(fs_group.value) <> 'object' OR NOT {source_ok('fs_group.value')}))"""


def _literal_match(column, keyword):
    literal = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return column.ilike(f"%{literal}%", escape="\\")


def _active_source(source_id, area):
    source = MapSource.__table__.alias()
    return select(source.c.id).where(source.c.id == source_id,
        source.c.operational_area_id == area, source.c.status == "active").exists()


def _identity_conditions(identity, asset):
    decision = FacilityIdentityDecision.__table__.alias()
    newer = FacilityIdentityDecision.__table__.alias()
    latest = ~select(newer.c.id).where(newer.c.identity_id == identity.c.id,
        newer.c.sequence > decision.c.sequence).correlate(identity, decision).exists()
    has_decision = select(decision.c.id).where(decision.c.identity_id == identity.c.id).correlate(identity).exists()
    bound = select(decision.c.id).where(decision.c.identity_id == identity.c.id,
        decision.c.operational_area_id == asset.operational_area_id,
        decision.c.action == "bind", decision.c.target_asset_id == asset.id, latest).correlate(identity, asset).exists()
    return and_(identity.c.operational_area_id == asset.operational_area_id,
        identity.c.asset_type == asset.asset_type,
        _active_source(identity.c.source_id, asset.operational_area_id),
        or_(and_(~has_decision, identity.c.native_asset_id == asset.id), bound))


def _matching_history(keyword, *, json_object=None):
    asset = JurisdictionAsset
    version = JurisdictionAssetVersion.__table__.alias()
    identity = FacilitySourceIdentity.__table__.alias()
    claim = MapFeatureClaim.__table__.alias()
    # Legacy snapshots may lack an area, but must never claim a different area.
    snapshot_area = version.c.snapshot["operational_area_id"].as_string()
    selected = version.c.id if json_object is None else json_object(
        "kind", "historical_name", "value", version.c.snapshot["name"].as_string(), "version_id", version.c.id)
    query = select(selected).where(version.c.asset_id == asset.id,
        _literal_match(version.c.snapshot["name"].as_string(), keyword),
        or_(snapshot_area.is_(None), snapshot_area == cast(asset.operational_area_id, String)),
        _VisibleSnapshotSources(version.c.snapshot, asset.operational_area_id),
        or_(version.c.source_claim_id.is_(None), select(claim.c.id).where(
            claim.c.id == version.c.source_claim_id, claim.c.asset_id == asset.id,
            _active_source(claim.c.source_id, asset.operational_area_id)).correlate(version, asset).exists()),
        or_(version.c.source_identity_id.is_(None), select(identity.c.id).where(
            identity.c.id == version.c.source_identity_id,
            _identity_conditions(identity, asset)).correlate(version, asset).exists()))
    return query.correlate(asset).order_by(version.c.version.desc(), version.c.id.desc()).limit(1)


def _matching_alias(keyword, *, json_object=None):
    identity = FacilitySourceIdentity.__table__.alias()
    selected = identity.c.id if json_object is None else json_object(
        "kind", "source_alias", "value", identity.c.source_record_id,
        "identity_id", identity.c.id, "source_id", identity.c.source_id)
    return select(selected).where(_identity_conditions(identity, JurisdictionAsset),
        identity.c.identity_kind == "exact_id", _literal_match(identity.c.source_record_id, keyword)
    ).correlate(JurisdictionAsset).order_by(identity.c.id).limit(1)


class FacilitySearchService:
    @staticmethod
    def filtered_query(db, *, keyword=None, operational_area_id=None, asset_type=None,
                       source=None, status="active"):
        # The ORM's current principal criteria apply to the outer asset query;
        # every referenced source/identity is constrained to that same area.
        query = db.query(JurisdictionAsset).filter(_VisibleSources(
            JurisdictionAsset.attributes, JurisdictionAsset.operational_area_id))
        for value, field in ((operational_area_id, JurisdictionAsset.operational_area_id),
                             (asset_type, JurisdictionAsset.asset_type),
                             (source, JurisdictionAsset.source), (status, JurisdictionAsset.status)):
            if value is not None and value != "":
                query = query.filter(field == value)
        if keyword and keyword.strip():
            term = keyword.strip()
            query = query.filter(or_(*[_literal_match(field, term) for field in (
                JurisdictionAsset.name, JurisdictionAsset.external_id, JurisdictionAsset.address)],
                _matching_history(term).exists(), _matching_alias(term).exists()))
        return query

    @staticmethod
    def items(db, *, limit=200, skip=0, **filters):
        term = (filters.get("keyword") or "").strip()
        query = FacilitySearchService.filtered_query(db, **filters).order_by(JurisdictionAsset.id.desc())
        if not term:
            rows = query.offset(skip).limit(limit).all()
            for row in rows:
                row.search_match = None
            return rows
        # Only selected page identities are materialized. Scalar lookups are
        # limited to one matching version/identity, not an in-memory full scan.
        json_object = func.json_build_object if db.get_bind().dialect.name == "postgresql" else func.json_object
        rows = query.add_columns(_matching_history(term, json_object=json_object).scalar_subquery(),
            _matching_alias(term, json_object=json_object).scalar_subquery()).offset(skip).limit(limit).all()
        result = []
        for row, historical_match, alias_match in rows:
            match = None
            for kind, value in (("current_name", row.name), ("external_id", row.external_id), ("address", row.address)):
                if value is not None and term.lower() in value.lower():
                    match = {"kind": kind, "value": value}
                    break
            if match is None:
                match = historical_match or alias_match
                if isinstance(match, str):
                    match = json.loads(match)
            row.search_match = match
            result.append(row)
        return result
