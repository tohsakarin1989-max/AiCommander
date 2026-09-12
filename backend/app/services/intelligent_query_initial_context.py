"""Typed page selection becomes server-frozen conditions, never an authority grant."""

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.models.case import Case
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_search_service import CaseSearchService
from app.services.intelligent_query_context import empty_conditions, remember
from app.services.intelligent_query_tools import CaseFilters


class InitialQueryContext(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_case_id: int | None = Field(default=None, gt=0, strict=True)
    filters: CaseFilters = Field(default_factory=CaseFilters)

    @model_validator(mode='after')
    def consistent(self):
        if (self.source_case_id is not None and self.filters.case_id is not None
                and self.source_case_id != self.filters.case_id):
            raise ValueError('query_initial_case_conflict')
        if self.source_case_id is None and not normalized_filters(self.filters):
            raise ValueError('query_initial_context_empty')
        return self


def normalized_filters(filters: CaseFilters) -> dict:
    values = filters.model_dump(mode='json', exclude_none=True)
    return {key: value for key, value in values.items()
            if value != [] and (not isinstance(value, str) or value.strip())}


def freeze_initial_context(db, value) -> dict:
    request = InitialQueryContext.model_validate(value)
    filters = normalized_filters(request.filters)
    allowed = db.info.get('authorized_area_ids')
    area = filters.get('operational_area_id')
    if 'authorized_area_ids' not in db.info or (area is not None and allowed is not None and area not in allowed):
        raise PermissionError('query_initial_context_unavailable')
    source_id = request.source_case_id or filters.get('case_id')
    source = None
    if source_id is not None:
        case = db.scalar(select(Case).where(Case.id == source_id)
                         .execution_options(populate_existing=True))
        if case is None:
            raise PermissionError('query_initial_context_unavailable')
        filters['case_id'] = case.id
        if area is None and case.operational_area_id is not None:
            filters['operational_area_id'] = case.operational_area_id
        # A contradictory area/category/time selection must not silently be discarded.
        typed_filters = CaseFilters.model_validate(filters)
        if CaseSearchService.filtered_query(db, **typed_filters.model_dump()).first() is None:
            raise ValueError('query_initial_context_conflict')
        source = {'case_id': case.id, 'operational_area_id': case.operational_area_id,
                  'source_hash': CasePipelineService.source_hash(db, case)}
    conditions = remember(empty_conditions(), 'find_cases', filters)
    return {'schema_version': 'query-initial-context-5.0-1', 'source_case': source,
            'conditions': conditions,
            'boundary': '从页面继承案件选择与筛选条件，不继承授权；案件内容仍由内网只读工具获取。'}


def require_source_case_version(db, context) -> None:
    source = (context or {}).get('source_case')
    if source is None:
        return
    if not isinstance(source, dict) or type(source.get('case_id')) is not int:
        raise PermissionError('query_initial_context_unavailable')
    case = db.scalar(select(Case).where(Case.id == source['case_id'])
                     .execution_options(populate_existing=True))
    if (case is None or case.operational_area_id != source.get('operational_area_id')
            or CasePipelineService.source_hash(db, case) != source.get('source_hash')):
        raise PermissionError('query_initial_context_changed')
