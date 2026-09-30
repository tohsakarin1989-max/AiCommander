"""Typed adapters over real business services; no generation or business writes."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset
from app.services.case_saved_profile import read_saved_profile
from app.services.case_result_service import CaseResultService


class BusinessArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operational_area_id: int | None = Field(default=None, gt=0, strict=True)


class ReadProcess(BusinessArgs):
    case_id: int = Field(gt=0, strict=True)
    keyword: str | None = Field(default=None, min_length=1, max_length=120)
    statuses: list[Annotated[str, Field(min_length=1, max_length=120)]] | None = Field(default=None, max_length=20)
    case_types: list[Annotated[str, Field(min_length=1, max_length=120)]] | None = Field(default=None, max_length=20)
    oil_types: list[Annotated[str, Field(min_length=1, max_length=120)]] | None = Field(default=None, max_length=20)
    start_date: AwareDatetime | None = None
    end_date: AwareDatetime | None = None
    has_geo: bool | None = Field(default=None, strict=True)

    @model_validator(mode='after')
    def ordered(self):
        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValueError('invalid_time_window')
        return self


class ExplainResult(ReadProcess):
    result_id: UUID | None = None


class ReadFacility(BusinessArgs):
    asset_id: int = Field(gt=0, strict=True)
    start_date: AwareDatetime | None = None
    end_date: AwareDatetime | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValueError("invalid_time_window")
        return self


class ReadFacilityAt(BusinessArgs):
    asset_id: int = Field(gt=0, strict=True)
    valid_at: AwareDatetime
    known_at: AwareDatetime


class ResourceMovement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_id: int = Field(gt=0, strict=True)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False, strict=True)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False, strict=True)


class CoverageScenario(BusinessArgs):
    operational_area_id: int = Field(gt=0, strict=True)
    as_of: AwareDatetime
    disabled_resource_ids: list[Annotated[int, Field(gt=0, strict=True)]] = Field(default_factory=list, max_length=100)
    movements: list[ResourceMovement] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_resources(self):
        moves = [item.resource_id for item in self.movements]
        if len(moves) != len(set(moves)) or len(self.disabled_resource_ids) != len(set(self.disabled_resource_ids)):
            raise ValueError("duplicate_scenario_resource")
        if set(moves) & set(self.disabled_resource_ids):
            raise ValueError("conflicting_scenario_changes")
        return self


ResultKind = Literal["case", "topic", "facility", "situation", "meeting", "experience", "conclusion"]


class FindBusinessResults(BusinessArgs):
    query: str = Field(default="", max_length=120)
    kind: ResultKind | None = None
    limit: int = Field(default=20, ge=1, le=50, strict=True)
    offset: int = Field(default=0, ge=0, le=10000, strict=True)


class ReadBusinessResult(BusinessArgs):
    kind: ResultKind
    identifier: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")


BUSINESS_TOOLS = {
    "read_case_process": ReadProcess, "explain_case_result": ExplainResult,
    "read_facility_dossier": ReadFacility, "read_facility_at": ReadFacilityAt,
    "compare_coverage_scenario": CoverageScenario,
    "find_business_results": FindBusinessResults, "read_business_result": ReadBusinessResult,
}


def _case(db, args):
    from app.services.case_search_service import CaseSearchService
    case = CaseSearchService.filtered_query(db, **args.model_dump(exclude={'result_id'})).populate_existing().first()
    if case is None or (args.operational_area_id is not None and case.operational_area_id != args.operational_area_id):
        raise PermissionError("query_case_unavailable")
    return case


def _asset(db, args):
    asset = db.scalar(select(JurisdictionAsset).where(JurisdictionAsset.id == args.asset_id)
                      .execution_options(populate_existing=True))
    if asset is None or (args.operational_area_id is not None and asset.operational_area_id != args.operational_area_id):
        raise PermissionError("query_facility_unavailable")
    return asset


def process_result(db, args):
    case = _case(db, args)
    saved = read_saved_profile(db, case)
    data = saved.get("data") or {}
    semantics = (data.get("payload") or {}).get("semantics") or {}
    if saved["status"] != "ready" or not semantics.get("process"):
        return {"state": "partial", "case_id": case.id, "process": None,
                "information_gaps": ["案件过程尚未就绪或来源版本已变化，等待后台更新；不重新处理原文。"]}
    partial = (semantics['process'].get('coverage') or {}).get('state') == 'partial'
    return {"state": "partial" if partial else "ready", "case_id": case.id, "case_number": case.case_number,
            "profile_id": data["id"], "source_hash": data["source_hash"],
            "source_revision_id": semantics["process"]["source_revision_id"],
            "process": deepcopy(semantics["process"]), "source_snapshot": deepcopy(semantics["source_snapshot"]),
            "evidence_refs": [f"case_profile:{data['id']}"],
            "information_gaps": [item if isinstance(item, str) else (item.get('message') or item.get('reason') or
                                  json.dumps(item, ensure_ascii=False)) for item in semantics.get("information_gaps", [])]}


def explain_result(db, args):
    case = _case(db, args)
    from app.models.case_result import CaseResultSnapshot
    if not args.result_id and not db.scalar(select(CaseResultSnapshot.id).where(
            CaseResultSnapshot.case_id == case.id).limit(1)):
        return {"state": "partial", "case_id": case.id, "result": None,
                "information_gaps": ["尚无可读取的冻结成果，不会为回答重新生成。"]}
    try:
        result = CaseResultService.read(db, str(args.result_id)) if args.result_id else CaseResultService.latest(db, case.id)
    except (ValueError, LookupError):
        return {"state": "partial", "case_id": case.id, "result": None,
                "information_gaps": ["尚无可读取的冻结成果，不会为回答重新生成。"]}
    content = result.get("content") or {}
    if content.get("case_id") != case.id:
        raise PermissionError("query_result_case_mismatch")
    return {"state": "ready" if args.result_id or result.get("freshness") == "current" else "partial",
            "case_id": case.id, "result": result,
            "result_basis": "specified_historical_result" if args.result_id else "current_result",
            "evidence_refs": [f"case_result:{result['id']}"],
            "information_gaps": list(result.get("composition_information_gaps", []))}


def execute_business_tool(db, name, args):
    if name == "read_case_process":
        return process_result(db, args)
    if name == "explain_case_result":
        return explain_result(db, args)
    if name == "read_facility_dossier":
        from app.services.facility_summary_service import read_dossier
        _asset(db, args)
        dossier = read_dossier(db, args.asset_id, start_date=args.start_date, end_date=args.end_date)
        partial = any(section.get("state") in {"partial", "restricted", "unavailable"}
                      for section in dossier.get("sections", {}).values())
        return {"state": "partial" if partial else "ready", "asset_id": args.asset_id, "dossier": dossier,
                "evidence_refs": [f"map_asset:{args.asset_id}"], "information_gaps": []}
    if name == "read_facility_at":
        from app.services.facility_identity_service import FacilityIdentityService
        from app.services.facility_execution_context import freeze_facility_context
        asset = _asset(db, args)
        context = freeze_facility_context(db, area_id=asset.operational_area_id,
                                          valid_at=args.valid_at, known_at=args.known_at)
        record = FacilityIdentityService.get_asset_at(db, asset.id, valid_at=context.valid_at, known_at=context.known_at)
        return {"state": "ready" if record.get("state") == "ready" else "partial", "asset_id": asset.id,
                "historical": record, "execution_context": context.public(),
                "evidence_refs": [f"map_asset:{asset.id}"],
                "information_gaps": [] if record.get("state") == "ready" else ["指定有效时间与已知时间没有可用资料，不能用现值替代。"]}
    if name == "compare_coverage_scenario":
        from app.services.spatial_coverage_service import compare_coverage
        computed = compare_coverage(db, args.operational_area_id, as_of=args.as_of,
            disabled_resource_ids=tuple(args.disabled_resource_ids),
            movements={item.resource_id: (item.latitude, item.longitude) for item in args.movements})
        partial = any(computed[key]["unknown_count"] for key in ("baseline", "scenario"))
        return {"state": "partial" if partial else "ready", "comparison": computed,
                "evidence_refs": computed["evidence_refs"], "information_gaps": [computed["boundary"]]}
    if name == "find_business_results":
        from app.services.result_catalog import catalog
        # Catalog kinds have their own typed scope, not an arbitrary area filter.
        if args.operational_area_id is not None:
            raise ValueError("query_context_tool_cannot_preserve_filters")
        result = catalog(db, query=args.query, kind=args.kind, limit=args.limit, offset=args.offset, exclude_kinds=('query',))
        result["items"] = [item for item in result.get("items", []) if item.get("kind") != "query"]
        return {"state": "ready" if result["items"] else "empty", "catalog": result,
                "information_gaps": ["仅本批成果目录，查询任务类型不进入助手工具以防递归引用。"]}
    if name == "read_business_result":
        from app.services.result_catalog import read_result
        if args.operational_area_id is not None:
            raise ValueError("query_context_tool_cannot_preserve_filters")
        result = read_result(db, args.kind, args.identifier, include_judgments=False)
        return {"state": "ready", "business_result": result,
                "evidence_refs": [f"business_result:{args.kind}:{args.identifier}"], "information_gaps": []}
    raise ValueError("query_tool_not_allowed")


def validate_business_query_evidence(db, result):
    """Re-authorize frozen cards; never silently replace their source or content."""
    from app.services.intelligent_query_context import result_hash
    for card in (result or {}).get("cards", []):
        name = card.get("tool")
        if name not in BUSINESS_TOOLS:
            continue
        arguments = BUSINESS_TOOLS[name].model_validate(card["evidence"]["filters"])
        old = card.get("data") or {}
        if name == "explain_case_result" and old.get("result"):
            arguments.result_id = UUID(old["result"]["id"])
            current = execute_business_tool(db, name, arguments)
            if current.get("result", {}).get("content_sha256") != old["result"].get("content_sha256"):
                raise PermissionError("query_business_evidence_changed")
        elif name == "compare_coverage_scenario":
            # Never recalculate a scenario when reading its historical answer.
            frozen = (old.get("comparison") or {}).get("input_snapshot") or {}
            for resource in [*frozen.get("resources", []), *frozen.get("targets", [])]:
                row = db.scalar(select(JurisdictionAsset).where(JurisdictionAsset.id == resource["id"])
                                .execution_options(populate_existing=True))
                if row is None or row.operational_area_id != frozen.get("area_id"):
                    raise PermissionError("query_business_evidence_changed")
        elif name == "find_business_results":
            from app.services.result_catalog import read_result
            for item in old.get("catalog", {}).get("items", []):
                current = read_result(db, item["kind"], item["id"])
                if current["content_sha256"] != item["content_sha256"]:
                    raise PermissionError("query_business_evidence_changed")
        else:
            current = execute_business_tool(db, name, arguments)
            if name == "read_facility_dossier":
                old_hash = old.get("dossier", {}).get("versions", {}).get("view_version")
                new_hash = current.get("dossier", {}).get("versions", {}).get("view_version")
            elif name == "read_business_result":
                old_hash = old.get("business_result", {}).get("content_sha256")
                new_hash = current.get("business_result", {}).get("content_sha256")
            elif name == "read_facility_at":
                old_hash, new_hash = result_hash(old.get("historical")), result_hash(current.get("historical"))
            else:
                old_hash, new_hash = result_hash(old), result_hash(current)
            if old_hash != new_hash:
                raise PermissionError("query_business_evidence_changed")
