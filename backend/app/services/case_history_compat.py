"""Legacy response shape over the single authorized history retrieval engine."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.case import Case
from app.services.case_history_retrieval import CaseHistoryRetrieval, HistoryUnavailable


def build_legacy_similar_cases(db: Session, case_id: int, days: int = 365,
                               limit: int = 10) -> dict:
    """Keep legacy consumers readable without inventing old scoring components."""
    if "authorized_area_ids" not in db.info:
        raise HistoryUnavailable("history_unavailable")
    base = db.scalar(select(Case).where(Case.id == case_id)
                     .execution_options(populate_existing=True))
    if base is None:
        raise HistoryUnavailable("history_unavailable")
    filters = ({"start_date": datetime.now(timezone.utc) - timedelta(days=days)}
               if days > 0 else {})
    # Database errors propagate to the API's explicit 503 boundary. Continuing
    # inside an aborted PostgreSQL transaction or rolling back a caller's writes
    # would both be incorrect here.
    result = CaseHistoryRetrieval.search_cases(
        db, source_case_id=case_id, filters=filters, limit=limit,
    )
    rows = {row.id: row for row in db.scalars(select(Case).where(
        Case.id.in_([item["case_id"] for item in result["items"]])
    ).execution_options(populate_existing=True))}
    labels = {"stated": "原文陈述", "negated": "原文否定", "uncertain": "待核表述", "inferred": "推断"}
    items = []
    for item in result["items"]:
        case = rows.get(item["case_id"])
        if case is None:
            continue
        shared = [f"{value}（{labels.get(kind, kind)}）"
                  for _, value, kind in item["shared_conditions"]]
        differences = [f"{value}：历史来源为{labels.get(kind, kind)}，与本案表述不同，需核对。"
                       for _, value, kind in item["different_conditions"]]
        brief = {field: getattr(case, field) for field in (
            "id", "case_number", "location", "latitude", "longitude", "case_type",
            "facility_type", "oil_nature", "source_type", "quality_score",
        )}
        brief["occurred_time"] = case.occurred_time.isoformat() if case.occurred_time else None
        items.append({**item, "case": brief, "similarity_score": round(item["score"] * 100, 4),
                      "reasons": [f"共同条件：{value}" for value in shared]
                      or ["仅词项或本地语义相关，尚无共同业务条件支持。"],
                      "shared_tags": shared, "matching_tags": shared,
                      "components": {}, "score_components": {}, "distance_km": None,
                      "duplicate_warnings": [], "warnings": differences,
                      "boundary": result["boundary"]})
    return {**{key: value for key, value in result.items() if key != "items"},
            "case_id": base.id, "case_number": base.case_number, "items": items,
            "principle": "采用统一全授权历史检索；保留肯定、否定、待核及差异。检索支持度不是概率，也不是旧版时间/距离加权分。"}
