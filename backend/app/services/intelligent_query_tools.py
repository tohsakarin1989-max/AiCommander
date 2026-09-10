"""Five bounded read tools. Returned business data stays inside the intranet.

This module does not call models or accept executable expressions. Callers must
bind the current principal's read scope before every execution, including replay.
"""
from datetime import datetime, timedelta, timezone
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, or_

from app.models.case_insight import CaseAnalysisRun
from app.models.jurisdiction import JurisdictionAsset
from app.services.case_search_service import CaseSearchService
from app.services.map_place_service import search_places
from app.services.intelligent_query_results import result_content


Label = Annotated[str, Field(min_length=1, max_length=120)]


class ScopeArgs(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operational_area_id: int | None = Field(default=None, gt=0, strict=True)

    @field_validator('*')
    @classmethod
    def normalize_dates(cls, value):
        if isinstance(value, datetime):
            try:
                return value.astimezone(timezone.utc)
            except OverflowError:
                raise ValueError('invalid_time_window') from None
        return value


class CaseFilters(ScopeArgs):
    keyword: Label | None = None
    statuses: list[Label] | None = Field(default=None, max_length=20)
    case_types: list[Label] | None = Field(default=None, max_length=20)
    oil_types: list[Label] | None = Field(default=None, max_length=20)
    start_date: AwareDatetime | None = None
    end_date: AwareDatetime | None = None
    has_geo: bool | None = Field(default=None, strict=True)

    @model_validator(mode='after')
    def ordered(self):
        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValueError('invalid_time_window')
        return self


class FindCases(CaseFilters):
    page: int = Field(default=1, ge=1, le=10000, strict=True)
    page_size: int = Field(default=20, ge=1, le=50, strict=True)


class ComparePeriods(ScopeArgs):
    start: AwareDatetime
    end: AwareDatetime
    case_types: list[Label] | None = Field(default=None, max_length=20)
    oil_types: list[Label] | None = Field(default=None, max_length=20)

    @model_validator(mode='after')
    def bounded(self):
        if not timedelta(0) < self.end - self.start <= timedelta(days=366):
            raise ValueError('invalid_time_window')
        try:
            self.start - (self.end - self.start)
        except OverflowError:
            raise ValueError('invalid_time_window') from None
        return self


class FindPlaces(ScopeArgs):
    keyword: Label
    include_public_places: bool = Field(default=False, strict=True)
    limit: int = Field(default=20, ge=1, le=50, strict=True)


class SummarizeResults(ScopeArgs):
    case_id: int | None = Field(default=None, gt=0, strict=True)
    completed_after: AwareDatetime | None = None
    completed_before: AwareDatetime | None = None
    limit: int = Field(default=20, ge=1, le=50, strict=True)

    @model_validator(mode='after')
    def ordered(self):
        if self.completed_after and self.completed_before and self.completed_after >= self.completed_before:
            raise ValueError('invalid_time_window')
        return self


TOOLS = {
    'find_cases': FindCases, 'find_places': FindPlaces, 'count_cases': CaseFilters,
    'compare_periods': ComparePeriods, 'summarize_results': SummarizeResults,
}


def tool_catalog() -> dict:
    return {name: schema.model_json_schema() for name, schema in TOOLS.items()}


def _cases(db, args):
    result = CaseSearchService.page(db, **args.model_dump())
    return {**{k: result[k] for k in ('total', 'page', 'page_size')}, 'items': [
        {'id': row.id, 'case_number': row.case_number, 'occurred_time': row.occurred_time,
         'case_type': row.case_type, 'location': row.location,
         'evidence_ref': f'case:{row.id}'} for row in result['items']]}


def _count(db, args):
    return CaseSearchService.page(db, page=1, page_size=1, **args)['total']


def _places(db, args):
    literal = args.keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    query = db.query(JurisdictionAsset).filter(or_(
        JurisdictionAsset.name.ilike(f'%{literal}%', escape='\\'),
        JurisdictionAsset.address.ilike(f'%{literal}%', escape='\\')))
    if args.operational_area_id is not None:
        query = query.filter(JurisdictionAsset.operational_area_id == args.operational_area_id)
    total = query.count()
    data = {'total': total, 'items': [
        {'id': row.id, 'name': row.name, 'asset_type': row.asset_type,
         'status': row.status, 'verified': row.verified, 'evidence_ref': f'map_asset:{row.id}'}
        for row in query.order_by(JurisdictionAsset.id).limit(args.limit).all()]}
    gaps = []
    if args.include_public_places:
        try:
            data['public_places'] = search_places(db, 'current', args.keyword,
                limit=args.limit, area_id=args.operational_area_id)
        except ValueError:
            # A missing/broken map index is not evidence of no such location.
            data['public_places'] = {'state': 'unavailable'}
            gaps.append('公共地名索引不可用或查询不符合索引要求，不能据此认定地点不存在。')
    return data, gaps


def _results(db, args):
    from app.models.case import Case
    query = db.query(CaseAnalysisRun).join(Case, Case.id == CaseAnalysisRun.case_id).filter(
        CaseAnalysisRun.status.in_(['completed', 'degraded']))
    if args.operational_area_id is not None:
        query = query.filter(Case.operational_area_id == args.operational_area_id)
    if args.case_id is not None:
        query = query.filter(CaseAnalysisRun.case_id == args.case_id)
    if args.completed_after is not None:
        query = query.filter(CaseAnalysisRun.completed_at >= args.completed_after.astimezone(timezone.utc))
    if args.completed_before is not None:
        query = query.filter(CaseAnalysisRun.completed_at < args.completed_before.astimezone(timezone.utc))
    statuses = dict(query.with_entities(CaseAnalysisRun.status, func.count(CaseAnalysisRun.id))
                    .group_by(CaseAnalysisRun.status).all())
    return {'total': sum(statuses.values()), 'by_status': statuses, 'items': [
        {'run_id': row.id, 'case_id': row.case_id, 'status': row.status,
         'completed_at': row.completed_at, 'algorithm_version': row.algorithm_version,
         'case_profile_id': row.case_profile_id, 'map_snapshot_id': row.map_snapshot_id,
         'evidence_ref': f'case_analysis_run:{row.id}', **result_content(db, row)}
        for row in query.order_by(CaseAnalysisRun.completed_at.desc(), CaseAnalysisRun.id)
        .limit(args.limit).all()]}


def execute_tool(db, tool: str, arguments: dict) -> dict:
    schema = TOOLS.get(tool)
    if schema is None:
        raise ValueError('query_tool_not_allowed')
    args = schema.model_validate(arguments)
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('query_read_scope_required')
    allowed = db.info['authorized_area_ids']
    if args.operational_area_id is not None and allowed is not None and args.operational_area_id not in allowed:
        raise PermissionError('query_area_forbidden')
    gaps = []
    with db.no_autoflush:
        if tool == 'find_cases':
            data, source = _cases(db, args), 'cases'
        elif tool == 'count_cases':
            data, source = {'count': _count(db, args.model_dump())}, 'cases'
        elif tool == 'compare_periods':
            filters = args.model_dump(exclude={'start', 'end'})
            previous_start = args.start - (args.end - args.start)
            current = _count(db, {**filters, 'start_date': args.start, 'end_date': args.end})
            previous = _count(db, {**filters, 'start_date': previous_start, 'end_date': args.start})
            data = {'current_count': current, 'previous_count': previous, 'change': current - previous,
                    'previous_start': previous_start, 'previous_end': args.start,
                    'current_start': args.start, 'current_end': args.end}
            source = 'cases'
        elif tool == 'find_places':
            data, gaps = _places(db, args)
            source = 'jurisdiction_assets_and_optional_public_index'
        else:
            data, source = _results(db, args), 'case_analysis_runs'
            gaps.append('汇总已有成果及可核验候选；规则支持度不是准确概率，历史候选不转为正式事实。')
            if any(item['content_state'] != 'ready' for item in data['items']):
                gaps.append('部分成果内容不可读取、证据不可核验或超过展示上限，已返回可用部分。')
    size = data.get('total', data.get('count', data.get('current_count', 0) + data.get('previous_count', 0)))
    public_items = data.get('public_places', {}).get('items', [])
    empty = size == 0 and not public_items
    if empty:
        gaps.append('当前授权范围与筛选条件下未返回记录，不代表其他范围不存在数据。')
    partial = (tool == 'find_places' and gaps) or (tool == 'summarize_results' and any(
        item['content_state'] != 'ready' for item in data['items']))
    return {'tool': tool, 'state': 'partial' if partial else ('empty' if empty else 'ready'),
            'data': data, 'information_gaps': gaps,
            'evidence': {'source': source, 'filters': args.model_dump(mode='json'),
                         'scope': None if allowed is None else sorted(allowed),
                         'queried_at': datetime.now(timezone.utc).isoformat(), 'tool_version': 'v4.0-read-tools-2'},
            'boundary': '内网只读查询；案件按案发时间、成果按完成时间，时间区间左闭右开；不是新增事实或执行指令。'}
