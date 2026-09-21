"""Topic views resolve frozen references; never run another analysis."""
import math
from time import monotonic

from app.models.case_pipeline import CaseAnalysisProfile
from app.models.case_result import CaseResultSnapshot
from app.models.case_road_artifact import CaseRoadArtifact
from app.models.deployment_advisor import SituationBrief
from app.models.map_foundation import MapSnapshot
from app.services.case_result_service import CaseResultService
from app.services.case_road_artifact_service import read_road_artifact
from app.services.deployment_advisor_service import DeploymentAdvisorService
from app.services.intelligent_query_context import result_hash
from app.services.topic_history import freeze_history, validate_history


def _brief(db, row):
    result = DeploymentAdvisorService.brief_to_dict(db, row)
    if result['status'] == 'unavailable' or not row.comparison_snapshot:
        raise PermissionError('topic_brief_unavailable')
    # Feedback is mutable and not part of this immutable period material.
    return {key: result[key] for key in ('id', 'period_type', 'period_start', 'period_end',
        'operational_area_id', 'summary', 'comparison_snapshot', 'algorithm_version',
        'scope_policy_version', 'evidence_refs', 'information_gaps')}


def freeze_references(db, aggregate, args, *, deadline):
    references = {'case_results': [], 'roads': [], 'briefs': [], 'maps': []}
    areas = set()
    for source in aggregate['source_manifest']:
        if source['operational_area_id'] is not None:
            areas.add(source['operational_area_id'])
    if args.operational_area_id is not None:
        areas.add(args.operational_area_id)
    for member in aggregate['members']:
        if monotonic() >= deadline:
            raise ValueError('topic_scan_incomplete')
        if member['profile_state'] not in {'ready', 'partial'}:
            continue
        # Only reuse a result attached to the exact profile in this topic revision.
        rows = db.query(CaseResultSnapshot).filter_by(case_id=member['case_id'],
            case_profile_id=member['profile_id']).order_by(CaseResultSnapshot.created_at.desc(), CaseResultSnapshot.id.desc())
        for row in rows:
            if monotonic() >= deadline:
                raise ValueError('topic_scan_incomplete')
            try:
                result = CaseResultService.read(db, row.id)
            except (PermissionError, ValueError):
                continue
            references['case_results'].append({'id': row.id, 'case_id': member['case_id'],
                                               'content_sha256': result['content_sha256']})
            # One latest readable road artifact per case, not a new calculation.
            for road in db.query(CaseRoadArtifact).filter_by(case_result_id=row.id).order_by(
                CaseRoadArtifact.created_at.desc(), CaseRoadArtifact.id.desc()):
                if monotonic() >= deadline:
                    raise ValueError('topic_scan_incomplete')
                try:
                    artifact = read_road_artifact(db, road.id)
                except (PermissionError, ValueError):
                    continue
                references['roads'].append({'id': road.id, 'case_id': member['case_id'],
                                           'content_sha256': artifact['content_sha256']})
                break
            break
    for area in sorted(areas):
        if monotonic() >= deadline:
            raise ValueError('topic_scan_incomplete')
        snapshot = db.query(MapSnapshot).filter_by(operational_area_id=area, status='current').order_by(
            MapSnapshot.published_at.desc(), MapSnapshot.id).first()
        if snapshot:
            references['maps'].append({'id': snapshot.id, 'operational_area_id': area,
                'version': snapshot.version, 'manifest_sha256': result_hash(snapshot.manifest)})
        for period in ('daily', 'weekly'):
            query = db.query(SituationBrief).filter_by(operational_area_id=area, period_type=period)
            if args.start_date is not None:
                query = query.filter(SituationBrief.period_end > args.start_date)
            if args.end_date is not None:
                query = query.filter(SituationBrief.period_start < args.end_date)
            # The latest existing material is contextual, not a recomputed topic count.
            row = query.order_by(SituationBrief.period_end.desc(), SituationBrief.generated_at.desc(), SituationBrief.id).first()
            if row is None:
                continue
            try:
                brief = _brief(db, row)
            except (ValueError, PermissionError):
                continue
            references['briefs'].append({'id': row.id, 'content_sha256': result_hash(brief)})
    references['history'] = freeze_history(db, aggregate, args, deadline=deadline)
    return references


def resolve_references(db, references):
    """Current access is checked for every dependency, including road permissions."""
    resolved = {'case_results': [], 'roads': [], 'briefs': [], 'maps': []}
    resolved['history'] = validate_history(db, references.get('history'))
    try:
        for ref in references.get('case_results', []):
            result = CaseResultService.read(db, ref['id'])
            if result['content_sha256'] != ref['content_sha256'] or result['content']['case_id'] != ref['case_id']:
                raise ValueError('result_changed')
            resolved['case_results'].append({'id': ref['id'], 'case_id': ref['case_id'],
                'content_sha256': ref['content_sha256'], 'versions': result['content']['versions'],
                'candidates': result['content']['candidates'], 'information_gaps': result['content']['information_gaps']})
        for ref in references.get('roads', []):
            result = read_road_artifact(db, ref['id'])
            if result['content_sha256'] != ref['content_sha256']:
                raise ValueError('road_changed')
            resolved['roads'].append({'id': ref['id'], 'case_id': ref['case_id'],
                'content_sha256': ref['content_sha256'], 'content': result['content']})
        for ref in references.get('briefs', []):
            row = db.query(SituationBrief).filter_by(id=ref['id']).first()
            if row is None:
                raise ValueError('brief_missing')
            result = _brief(db, row)
            if result_hash(result) != ref['content_sha256']:
                raise ValueError('brief_changed')
            resolved['briefs'].append(result)
        for ref in references.get('maps', []):
            row = db.query(MapSnapshot).filter_by(id=ref['id'], operational_area_id=ref['operational_area_id']).first()
            if row is None or row.version != ref['version'] or result_hash(row.manifest) != ref['manifest_sha256']:
                raise ValueError('map_changed')
            resolved['maps'].append(ref)
    except (KeyError, ValueError, TypeError) as error:
        raise PermissionError('topic_reference_unavailable') from error
    return resolved


def snapshot_views(db, snapshot, *, page=1, page_size=20):
    aggregate = snapshot.payload['aggregate']
    members = aggregate['members'][(page - 1) * page_size:page * page_size]
    ids = {row['case_id'] for row in members}
    sources = {row['case_id']: row for row in aggregate['source_manifest'] if row['case_id'] in ids}
    points, timeline = [], []
    for member in members:
        if member['profile_state'] not in {'ready', 'partial'}:
            continue
        profile = db.query(CaseAnalysisProfile).filter_by(id=member['profile_id']).first()
        if profile is None:
            raise PermissionError('topic_reference_unavailable')
        facts = profile.payload.get('analysis_facts') or {}
        lat, lon = facts.get('latitude'), facts.get('longitude')
        when = (profile.payload.get('standard') or {}).get('occurred_time')
        timeline.append({'case_id': member['case_id'], 'occurred_time': when,
                         'profile_id': profile.id, 'profile_version': profile.profile_version})
        if (type(lat) in (int, float) and type(lon) in (int, float)
                and math.isfinite(lat) and math.isfinite(lon) and abs(lat) <= 85 and abs(lon) <= 180):
            points.append({'case_id': member['case_id'], 'latitude': lat, 'longitude': lon,
                'operational_area_id': sources[member['case_id']]['operational_area_id'], 'profile_id': profile.id})
    groups = [{**row, 'case_ids': [identifier for identifier in row['case_ids'] if identifier in ids]}
              for row in aggregate['patterns'] if ids.intersection(row['case_ids'])]
    references = resolve_references(db, snapshot.payload.get('references', {}))
    return {
        'snapshot_id': snapshot.id, 'content_sha256': snapshot.content_sha256,
        'map': {'points': points, 'versions': references['maps'],
                'unmapped_in_page': len(members) - len(points)},
        'graph': {'groups': groups, 'case_ids': sorted(ids),
                  'boundary': '连线只代表共享表述，不是正式案件关系或实际轨迹。'},
        'timeline': sorted(timeline, key=lambda row: (row['occurred_time'] or '', row['case_id'])),
        'case_results': [row for row in references['case_results'] if row['case_id'] in ids],
        'roads': [row for row in references['roads'] if row['case_id'] in ids],
        'period_materials': references['briefs'],
        'history': references['history'],
        'boundary': '地图、图谱、时间线和案例按同一成果分页；总体计数不分页。日/周材料为同辖区既有背景，未套用本专题语义条件，不与专题统计相加。',
    }
