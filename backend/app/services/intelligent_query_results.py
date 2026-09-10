"""Read existing insight content only after resolving its current evidence scope."""
import re

from app.models.case import Case
from app.models.case_insight import CaseHypothesis
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSnapshot, MapSnapshotFeature


def result_content(db, run):
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
