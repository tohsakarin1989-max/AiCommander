"""Current, source-backed road inputs without modifying legacy result fixtures."""
from app.models.case import Case
from app.models.case_source import CaseLocation
from app.services.case_analysis_applicability import allows
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_source_service import CaseSourceService


def rebuild_applicable_profile(db, profile, *, latitude=46.0, longitude=125.0):
    """Rebuild through real rules, never inject an applicability mask."""
    case = db.get(Case, profile.case_id)
    case.description = "合成记录：现场明确记录打孔盗油痕迹。"
    case.location = "合成案发点"
    point = db.query(CaseLocation).filter_by(case_id=case.id, role="incident").one_or_none()
    if point is None:
        point = CaseLocation(case_id=case.id, role="incident")
        db.add(point)
    point.description = "合成案发点"
    point.precision = "exact"
    point.geometry = {"type": "Point", "coordinates": [longitude, latitude]}
    point.source_note = "仅用于任务事务、权限与条件传递测试"
    db.flush()
    CaseSourceService.capture_change(db, case)
    payload = CasePipelineService.build_profile_payload(db, case)
    profile.payload = payload
    profile.source_hash = payload["source_hash"]
    profile.source_revision_id = payload["source_revision_id"]
    profile.schema_version = payload["schema_version"]
    profile.dictionary_version = payload["dictionary_version"]
    assert allows(payload, "road_analysis")
    db.commit()
    return profile
