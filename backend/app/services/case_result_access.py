"""统一成果交付前的当前授权校验；不向调用方披露不可访问的引用内容。"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_insight import CaseAnalysisRun
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSnapshot, MapSnapshotFeature
from app.services.case_result_snapshot import RESULT_SCHEMA_VERSION, verify_snapshot


class CaseResultAccessError(PermissionError):
    def __init__(self):
        super().__init__("case_result_unavailable")


def require_result_access(db: Session, snapshot: dict) -> None:
    """仅接收服务端保存的快照，每次读取/导出重新查询，不信任身份映射缓存。

    调用方必须在请求中绑定当前主体范围；未绑定的后台会话不能用于交付。
    hash并非签名，因此本函数不允许把用户上传内容当作可信成果。
    """
    if "authorized_area_ids" not in db.info or not verify_snapshot(snapshot):
        raise CaseResultAccessError()
    try:
        content = snapshot["content"]
        versions = content["versions"]
        case_id = content["case_id"]
        if content["schema_version"] != RESULT_SCHEMA_VERSION or type(case_id) is not int:
            raise CaseResultAccessError()
        if db.scalar(select(Case.id).where(Case.id == case_id)) is None:
            raise CaseResultAccessError()
        profile = db.execute(select(
            CaseAnalysisProfile.case_id, CaseAnalysisProfile.profile_version,
            CaseAnalysisProfile.source_hash, CaseAnalysisProfile.schema_version,
            CaseAnalysisProfile.dictionary_version,
        ).where(CaseAnalysisProfile.id == versions["case_profile_id"])).first()
        expected = (case_id, versions["profile_version"], versions["case_source_hash"],
                    versions["profile_schema"], versions["dictionary_version"])
        if profile is None or tuple(profile) != expected:
            raise CaseResultAccessError()
        map_id = versions["map_snapshot_id"]
        run_id = versions["analysis_run_id"]
        if run_id is not None:
            run = db.execute(select(
                CaseAnalysisRun.case_id, CaseAnalysisRun.case_profile_id,
                CaseAnalysisRun.map_snapshot_id, CaseAnalysisRun.algorithm_version,
            ).where(CaseAnalysisRun.id == run_id)).first()
            if run is None or tuple(run) != (
                case_id, versions["case_profile_id"], map_id, versions["algorithm_version"],
            ):
                raise CaseResultAccessError()
            if db.scalar(select(MapSnapshot.id).where(MapSnapshot.id == map_id)) is None:
                raise CaseResultAccessError()
        elif map_id is not None or versions["algorithm_version"] is not None or content["candidates"]:
            raise CaseResultAccessError()
        refs = list(content["facts_summary"]["evidence_refs"])
        for candidate in content["candidates"]:
            refs.extend(candidate["evidence_refs"])
        for ref in set(refs):
            _require_evidence_access(db, ref, map_id)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise CaseResultAccessError() from None


def _require_evidence_access(db: Session, ref: str, map_id: str | None) -> None:
    if not isinstance(ref, str):
        raise CaseResultAccessError()
    if match := re.fullmatch(r"case:([1-9][0-9]*)", ref):
        exists = db.scalar(select(Case.id).where(Case.id == int(match[1])))
    elif match := re.fullmatch(r"case_profile:([A-Za-z0-9_-]{1,36})", ref):
        exists = db.scalar(select(CaseAnalysisProfile.id).where(CaseAnalysisProfile.id == match[1]))
    elif match := re.fullmatch(r"map_asset:([1-9][0-9]*)@snapshot:([A-Za-z0-9_-]{1,36})", ref):
        if match[2] != map_id:
            raise CaseResultAccessError()
        asset_id = int(match[1])
        exists = db.scalar(select(MapSnapshotFeature.id).where(
            MapSnapshotFeature.snapshot_id == map_id, MapSnapshotFeature.asset_id == asset_id,
        ))
        # 历史快照仍保留旧辖区；源要素转移/删除后不能靠旧快照绕过当前权限。
        if db.scalar(select(JurisdictionAsset.id).where(JurisdictionAsset.id == asset_id)) is None:
            raise CaseResultAccessError()
    else:
        raise CaseResultAccessError()
    if exists is None:
        raise CaseResultAccessError()
