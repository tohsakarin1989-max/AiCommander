"""只读案件检索：先授权和筛选，再分页；分类计数不受页大小影响。"""
from datetime import datetime

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.case import Case
from app.services.case_time_window import filter_case_time_window


class CaseSearchService:
    @staticmethod
    def filtered_query(
        db: Session,
        *,
        keyword: str | None = None,
        statuses: list[str] | None = None,
        case_types: list[str] | None = None,
        oil_types: list[str] | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        has_geo: bool | None = None,
        operational_area_id: int | None = None,
        case_id: int | None = None,
        include_categories: bool = True,
        time_basis: str | None = None,
    ):
        # 使用 ORM 保持 database.py 对查询、分类聚合和计数的一致范围控制。
        query = db.query(Case)
        if case_id is not None:
            query = query.filter(Case.id == case_id)
        if operational_area_id is not None:
            query = query.filter(Case.operational_area_id == operational_area_id)
        if keyword and keyword.strip():
            literal = keyword.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.filter(or_(*(
                field.ilike(f"%{literal}%", escape="\\")
                # Original scalar fields only: stale derived feature JSON is
                # not silently promoted to a source fact by keyword matching.
                for field in (Case.case_number, Case.location, Case.description, Case.case_type,
                    Case.modus_operandi, Case.upstream_source, Case.downstream_destination,
                    Case.source_detail, Case.facility_type, Case.facility_owner,
                    Case.oil_type, Case.oil_nature, Case.source_type, Case.report_unit)
            )))
        query = filter_case_time_window(query, start_date, end_date, time_basis=time_basis)
        if has_geo is True:
            query = query.filter(Case.latitude.isnot(None), Case.longitude.isnot(None))
        elif has_geo is False:
            query = query.filter(or_(Case.latitude.is_(None), Case.longitude.is_(None)))
        if include_categories:
            for values, field in ((statuses, Case.status), (case_types, Case.case_type), (oil_types, Case.oil_type)):
                if values:
                    query = query.filter(field.in_(values))
        return query

    @staticmethod
    def page(db: Session, *, page: int, page_size: int, keyword=None, statuses=None,
             case_types=None, oil_types=None, start_date=None, end_date=None,
             has_geo=None, operational_area_id=None, case_id=None, time_basis=None) -> dict:
        query = CaseSearchService.filtered_query(db, keyword=keyword, start_date=start_date,
            end_date=end_date, has_geo=has_geo, operational_area_id=operational_area_id, case_id=case_id,
            include_categories=False, time_basis=time_basis)

        # 分类计数基于授权 + 关键词 + 日期 + 坐标条件，故多选后仍可发现其他分类。
        facets = {}
        for name, field in (("statuses", Case.status), ("case_types", Case.case_type), ("oil_types", Case.oil_type)):
            rows = query.with_entities(field, func.count(Case.id)).group_by(field).order_by(field).all()
            facets[name] = {value: count for value, count in rows if value}
        for values, field in ((statuses, Case.status), (case_types, Case.case_type), (oil_types, Case.oil_type)):
            if values:
                query = query.filter(field.in_(values))

        total = query.count()
        time_field = {'discovery': Case.discovered_at, 'entry': Case.created_at}.get(time_basis, Case.occurred_time)
        # PostgreSQL DESC defaults to NULLS FIRST; unknown dates must not displace
        # known recent records. The ID tie-breaker keeps pagination stable.
        items = query.order_by(time_field.desc().nulls_last(), Case.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return {"items": items, "total": total, "page": page, "page_size": page_size, "facets": facets}
