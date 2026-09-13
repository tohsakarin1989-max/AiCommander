"""日常大屏只读汇总；统计不依赖前端分页或坐标样本。"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_insight import CaseAnalysisRun, CaseHypothesis
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.map_foundation import MapSnapshot
from app.models.jurisdiction import JurisdictionAsset
from app.utils.datetimes import utc_datetime
from app.services.intelligent_query_results import result_content
from app.services.dashboard_activity_service import dashboard_activity


class DashboardSummaryService:
    @staticmethod
    def build(db: Session, *, operational_area_id: int | None, days: int,
              as_of: datetime | None = None, map_limit: int = 500, activity_limit: int = 20) -> dict:
        end = utc_datetime(as_of or datetime.now(timezone.utc))
        start = end - timedelta(days=days)
        previous_start = start - timedelta(days=days)
        cases = db.query(Case)
        wells = db.query(JurisdictionAsset).filter(
            JurisdictionAsset.asset_type == "well", JurisdictionAsset.status == "active")
        if operational_area_id is not None:
            cases = cases.filter(Case.operational_area_id == operational_area_id)
            wells = wells.filter(JurisdictionAsset.operational_area_id == operational_area_id)
        current = cases.filter(Case.occurred_time >= start, Case.occurred_time < end)
        previous = cases.filter(Case.occurred_time >= previous_start, Case.occurred_time < start)
        current_count, previous_count = current.count(), previous.count()

        # SQLite 时间按 UTC 存储；按北京时间归桶，PostgreSQL 使用显式时区转换。
        day_expression = (func.date(func.datetime(Case.occurred_time, "+8 hours"))
                          if db.get_bind().dialect.name == "sqlite"
                          else func.date(func.timezone("Asia/Shanghai", Case.occurred_time)))
        day_counts = {str(day): count for day, count in current.with_entities(
            day_expression, func.count(Case.id)).group_by(day_expression).all()}
        business_timezone = timezone(timedelta(hours=8))
        day = start.astimezone(business_timezone).date()
        last_day = (end - timedelta(microseconds=1)).astimezone(business_timezone).date()
        trend = []
        while day <= last_day:
            trend.append({"date": day.isoformat(), "count": day_counts.get(day.isoformat(), 0)})
            day += timedelta(days=1)

        mapped = current.filter(Case.latitude.between(-90, 90), Case.longitude.between(-180, 180))
        coordinate_count = mapped.count()
        map_cases = mapped.order_by(Case.occurred_time.desc(), Case.id.desc()).limit(map_limit).all()
        map_wells = wells.filter(JurisdictionAsset.latitude.between(-90, 90),
                                 JurisdictionAsset.longitude.between(-180, 180))
        mapped_well_count = map_wells.count()
        well_items = map_wells.order_by(JurisdictionAsset.id).limit(map_limit).all()

        # 成果按生成时间，而不是关联案件发生时间计数；再次用案件查询约束范围。
        analysis_query = db.query(CaseAnalysisRun).filter(
            CaseAnalysisRun.case_id.in_(cases.with_entities(Case.id)),
            CaseAnalysisRun.status.in_(["completed", "degraded"]),
            CaseAnalysisRun.completed_at >= start, CaseAnalysisRun.completed_at < end)
        analyses = analysis_query.count()

        def type_counts(query):
            return dict(query.with_entities(Case.case_type, func.count(Case.id)).group_by(Case.case_type).all())

        current_types, previous_types = type_counts(current), type_counts(previous)
        increases = [(category, count, count - previous_types.get(category, 0))
                     for category, count in current_types.items() if count > previous_types.get(category, 0)]
        increases.sort(key=lambda item: (-item[2], -item[1], item[0] or ""))
        attention = []
        for category, count, delta in increases[:3]:
            examples = current.filter(Case.case_type == category).order_by(
                Case.occurred_time.desc(), Case.id.desc()).limit(3).all()
            attention.append({
                "kind": "observed_change", "case_type": category,
                "title": f"{category or '未分类案件'}较上期增加 {delta} 起",
                "current_count": count, "previous_count": count - delta,
                "evidence": [{"case_id": item.id, "case_number": item.case_number,
                              "latitude": item.latitude, "longitude": item.longitude} for item in examples],
                "boundary": "数量变化事实，不代表风险等级或因果关系；下列为样例案件，非全部统计依据。",
            })

        # Latest existing candidates, not a new risk score or automatic decision.
        # Keep at least one observed change when present; never exceed three items.
        insight_attention = []
        seen_cases = set()
        candidate_runs = analysis_query.join(CaseAnalysisProfile,
            CaseAnalysisProfile.id == CaseAnalysisRun.case_profile_id).join(MapSnapshot,
            MapSnapshot.id == CaseAnalysisRun.map_snapshot_id).filter(
            CaseAnalysisProfile.is_current.is_(True),
            CaseAnalysisProfile.case_id == CaseAnalysisRun.case_id, MapSnapshot.status == 'current',
            CaseAnalysisRun.id.in_(
            db.query(CaseHypothesis.analysis_run_id).filter(CaseHypothesis.status == 'candidate'))
        ).order_by(CaseAnalysisRun.completed_at.desc(), CaseAnalysisRun.id)
        limit = 2 if attention else 3
        scan_limit = 50
        run_window = candidate_runs.limit(scan_limit + 1).all()
        for run in run_window[:scan_limit]:
            if run.case_id in seen_cases:
                continue
            content = result_content(db, run)
            candidates = [item for item in content['hypotheses'] if item['status'] == 'candidate']
            if not candidates:
                continue
            case = cases.filter(Case.id == run.case_id).first()
            if case is None:
                continue
            item = candidates[0]
            insight_attention.append({
                **item, 'kind': 'existing_insight', 'case_type': case.case_type,
                'run_id': run.id, 'completed_at': run.completed_at,
                'case_profile_id': run.case_profile_id, 'map_snapshot_id': run.map_snapshot_id,
                'algorithm_version': run.algorithm_version,
                'evidence': [{'case_id': case.id, 'case_number': case.case_number,
                              'latitude': case.latitude, 'longitude': case.longitude}],
            })
            seen_cases.add(case.id)
            if len(insight_attention) >= limit:
                break
        attention = insight_attention + attention[:3 - len(insight_attention)]

        well_count = wells.count()
        activity = dashboard_activity(db, cases, analysis_query, start=start, end=end, limit=activity_limit)
        return {
            **activity,
            "schema_version": 1, "operational_area_id": operational_area_id,
            "as_of": end, "state": "ready" if current_count or well_count or analyses or activity["activities"] else "empty",
            "period": {"start": start, "end": end, "previous_start": previous_start,
                       "previous_end": start, "days": days, "timezone": "Asia/Shanghai"},
            "metrics": {"cases": current_count, "previous_cases": previous_count,
                        "change": current_count - previous_count, "registered_wells": well_count,
                        "analysis_results": analyses},
            "definitions": {"cases": "完整授权范围、按案发时间，含缺坐标案件；起止区间左闭右开",
                            "registered_wells": "查询时范围内状态为 active 的登记井数，非历史井数",
                            "analysis_results": "本期完成或降级完成的双域研判运行次数，按完成时间，含历史案件重算；不等同于已保存成果份数",
                            "trend": "按北京时间自然日归桶，首尾可能为不足一天的时段"},
            "trend": trend, "attention": attention,
            "attention_scan": {"limit": scan_limit, "truncated": len(run_window) > scan_limit,
                               "ordering": "completed_at_desc"},
            "map": {"cases": [{"id": item.id, "case_number": item.case_number,
                               "latitude": item.latitude, "longitude": item.longitude,
                               "case_type": item.case_type} for item in map_cases],
                    "wells": [{"id": item.id, "name": item.name, "latitude": item.latitude,
                               "longitude": item.longitude} for item in well_items],
                    "coordinate_cases": coordinate_count,
                    "missing_coordinate_cases": current_count - coordinate_count,
                    "coordinate_wells": mapped_well_count,
                    "cases_truncated": coordinate_count > len(map_cases),
                    "wells_truncated": mapped_well_count > len(well_items)},
        }
