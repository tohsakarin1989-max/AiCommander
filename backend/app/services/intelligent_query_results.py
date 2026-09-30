"""Read existing insight content only after resolving its current evidence scope."""
import re

from app.models.case import Case
from app.models.case_insight import CaseHypothesis, CaseAnalysisRun
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSnapshot, MapSnapshotFeature
from app.models.case_result import CaseResultSnapshot
from app.services.case_result_service import CaseResultService


def result_content(db, run, *, matched_run_only=False):
    """Current consumers prefer exactly the same frozen result as the case page.

    Pre-snapshot historical runs remain readable and explicitly labeled; failure
    to authorize a frozen result never falls through to legacy run text.
    """
    snapshots = db.query(CaseResultSnapshot).filter(CaseResultSnapshot.case_id == run.case_id)
    if matched_run_only:
        snapshots = snapshots.filter(CaseResultSnapshot.content['versions']['analysis_run_id'].as_string() == run.id)
    exists = snapshots.first()
    if exists:
        try:
            if matched_run_only:
                # A date-filtered request names historical runs. It must never
                # silently switch from that run to a newer case composition.
                from app.services.case_result_composition import COMPOSITION_SCHEMA_VERSION
                result = None
                for row in snapshots.order_by(
                    (CaseResultSnapshot.content['schema_version'].as_string() == COMPOSITION_SCHEMA_VERSION).desc(),
                    CaseResultSnapshot.created_at.desc(), CaseResultSnapshot.id.desc()):
                    try:
                        result = CaseResultService.read(db, row.id)
                        break
                    except PermissionError:
                        continue
                if result is None:
                    raise PermissionError('query_result_unavailable')
            else:
                result = CaseResultService.latest(db, run.case_id)
        except PermissionError:
            return {'summary': None, 'hypotheses': [], 'content_state': 'unavailable',
                    'information_gaps': ['当前冻结成果不可交付；不使用其他来源绕过权限。']}
        content = result['content']
        from app.services.case_result_composition import COMPOSITION_SCHEMA_VERSION
        ready = ((result.get('composition_status') == 'ready' and result.get('freshness') == 'current')
                 or (matched_run_only and content['schema_version'] == COMPOSITION_SCHEMA_VERSION))
        source_run = db.query(CaseAnalysisRun).filter_by(id=content['versions']['analysis_run_id']).first()
        return {'result_id': result['id'], 'content_sha256': result['content_sha256'],
                'run_id': content['versions']['analysis_run_id'],
                'completed_at': source_run.completed_at if source_run else None,
                'status': content['analysis_status'],
                'algorithm_version': ((content.get('road_algorithm_versions') or {}).get('scorer')
                                      if ready else content['versions'].get('algorithm_version')),
                'road_algorithm_versions': content.get('road_algorithm_versions'),
                'road_versions': content.get('road_versions'),
                'evidence_ref': f"case_result:{result['id']}",
                'case_profile_id': content['versions']['case_profile_id'],
                'map_snapshot_id': content['versions']['map_snapshot_id'],
                'result_created_at': result['created_at'],
                'summary': ('历史冻结道路组合；不代表当前条件' if matched_run_only else '道路前置设施候选') if ready else '基础成果；道路组合未就绪',
                'is_current_composition': ready and not matched_run_only,
                'candidate_source': content.get('candidate_source', 'legacy_spatial_base'),
                'hypotheses': [{**item, 'hypothesis_type': item['category'], 'rule_support': item['score']}
                               for item in content['candidates']] if ready else [],
                'content_state': 'ready' if ready else 'partial',
                'information_gaps': [*content['information_gaps']['analysis'],
                                     *result.get('composition_information_gaps', [])],
                'versions': content['versions'], 'composition': content.get('composition')}
    historical = _legacy_result_content(db, run)
    return {**historical, 'run_id': run.id, 'status': run.status, 'completed_at': run.completed_at,
            'algorithm_version': run.algorithm_version, 'case_profile_id': run.case_profile_id,
            'map_snapshot_id': run.map_snapshot_id, 'evidence_ref': f'case_analysis_run:{run.id}',
            'candidate_source': 'historical_run_without_snapshot',
            'is_current_composition': False,
            'information_gaps': [*historical['information_gaps'], '历史运行尚未形成统一冻结成果；不是当前道路组合。']}


def _legacy_result_content(db, run):
    # Deliberately query instead of Session.get: cached ORM objects do not prove
    # current authorization after a scope change within the same session.
    profile = db.query(CaseAnalysisProfile.id).filter(
        CaseAnalysisProfile.id == run.case_profile_id,
        CaseAnalysisProfile.case_id == run.case_id).first()
    snapshot = db.query(MapSnapshot.id).filter(MapSnapshot.id == run.map_snapshot_id).first()
    withheld = {'summary': None, 'hypotheses': [], 'content_state': 'unavailable',
                'information_gaps': ['成果输入版本不可读取或已缺失，正文暂不展示。']}
    if not profile or not snapshot:
        return withheld

    def visible(ref):
        if not isinstance(ref, str):
            return False
        match = re.fullmatch(r'case:([1-9][0-9]*)', ref)
        if match:
            return db.query(Case.id).filter(Case.id == int(match[1])).first() is not None
        match = re.fullmatch(r'case_profile:([^:@\s]{1,36})', ref)
        if match:
            return db.query(CaseAnalysisProfile.id).filter(
                CaseAnalysisProfile.id == match[1]).first() is not None
        match = re.fullmatch(r'map_asset:([1-9][0-9]*)@snapshot:([^:@\s]{1,36})', ref)
        if match:
            asset_id, snapshot_id = int(match[1]), match[2]
            if snapshot_id != run.map_snapshot_id:
                return False
            feature = db.query(MapSnapshotFeature.id).filter(
                MapSnapshotFeature.snapshot_id == snapshot_id,
                MapSnapshotFeature.asset_id == asset_id).first()
            # Require both current asset access and frozen evidence access.
            asset = db.query(JurisdictionAsset.id).filter(JurisdictionAsset.id == asset_id).first()
            return feature is not None and asset is not None
        return False

    rows = db.query(CaseHypothesis).filter(
        CaseHypothesis.analysis_run_id == run.id,
        CaseHypothesis.case_id == run.case_id).order_by(CaseHypothesis.rank).all()
    items = []
    hidden = False
    for item in rows:
        refs = item.evidence_refs
        if not isinstance(refs, list) or not refs or not all(visible(ref) for ref in refs):
            hidden = True
            continue
        items.append({
            'id': item.id, 'hypothesis_type': item.hypothesis_type, 'rank': item.rank,
            'title': item.title, 'claim': item.claim, 'rule_support': item.score,
            'status': item.status, 'evidence_refs': refs,
            'supporting_evidence': item.supporting_evidence,
            'counter_evidence': item.counter_evidence,
            'information_gaps': item.information_gaps, 'boundary': item.boundary,
        })
    # A run summary/gap can itself quote a now-hidden candidate: withhold it too.
    return {'summary': None if hidden else run.summary, 'hypotheses': items[:3],
            'content_state': 'partial' if hidden or len(items) > 3 else 'ready',
            'information_gaps': (['部分证据不可核验，相关正文和运行摘要暂不展示。']
                                 if hidden else run.information_gaps),
            'truncated': len(items) > 3}
