"""只读案件检索：先授权和筛选，再分页；分类计数不受页大小影响。"""
from datetime import datetime

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.case import Case
from app.utils.datetimes import utc_datetime


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
        include_categories: bool = True,
    ):
        # 使用 ORM 保持 database.py 对查询、分类聚合和计数的一致范围控制。
        query = db.query(Case)
        if operational_area_id is not None:
            query = query.filter(Case.operational_area_id == operational_area_id)
        if keyword and keyword.strip():
            literal = keyword.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.filter(or_(*(
                field.ilike(f"%{literal}%", escape="\\")
                for field in (Case.case_number, Case.location, Case.description, Case.case_type)
            )))
        if start_date is not None:
            query = query.filter(Case.occurred_time >= utc_datetime(start_date))
        if end_date is not None:
            query = query.filter(Case.occurred_time < utc_datetime(end_date))
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
             has_geo=None, operational_area_id=None) -> dict:
        query = CaseSearchService.filtered_query(db, keyword=keyword, start_date=start_date,
            end_date=end_date, has_geo=has_geo, operational_area_id=operational_area_id,
            include_categories=False)

        # 分类计数基于授权 + 关键词 + 日期 + 坐标条件，故多选后仍可发现其他分类。
        facets = {}
        for name, field in (("statuses", Case.status), ("case_types", Case.case_type), ("oil_types", Case.oil_type)):
            rows = query.with_entities(field, func.count(Case.id)).group_by(field).order_by(field).all()
            facets[name] = {value: count for value, count in rows if value}
        for values, field in ((statuses, Case.status), (case_types, Case.case_type), (oil_types, Case.oil_type)):
            if values:
                query = query.filter(field.in_(values))

        total = query.count()
        items = query.order_by(Case.occurred_time.desc(), Case.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return {"items": items, "total": total, "page": page, "page_size": page_size, "facets": facets}
