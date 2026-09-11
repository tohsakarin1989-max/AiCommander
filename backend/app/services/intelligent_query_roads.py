"""Read frozen road results; never starts an engine, graph build or mutation."""
import math

from app.models.case import Case
from app.models.case_road_artifact import CaseRoadArtifact
from app.services.case_search_service import CaseSearchService
from app.services.case_road_artifact_service import read_road_artifact


def road_results(db, args):
    filters = args.model_dump(exclude={'page', 'page_size', 'min_detour_ratio'})
    # Reuse identical case filtering, including unpaginated authorized cases.
    cases = CaseSearchService.filtered_query(db, **filters).with_entities(Case.id)
    ids = [row.id for row in db.query(CaseRoadArtifact.id).join(Case, Case.id == CaseRoadArtifact.case_id)
        .filter(Case.id.in_(cases.statement))
        .order_by(CaseRoadArtifact.created_at.desc(), CaseRoadArtifact.id.desc())
        .offset((args.page - 1) * args.page_size).limit(args.page_size + 1).all()]
    items, withheld = [], False
    for identifier in ids[:args.page_size]:
        try:
            artifact = read_road_artifact(db, identifier)
        except (ValueError, PermissionError):
            # No forbidden road names, identifiers, counts or geometry returned.
            withheld = True
            continue
        content = artifact['content']
        route = content.get('route')
        calculation = route if route is not None else content['matrix']
        if args.min_detour_ratio is not None:
            ratio = (route or {}).get('detour_reference', {}).get('ratio')
            if type(ratio) not in (int, float) or not math.isfinite(ratio) or ratio < args.min_detour_ratio:
                continue
        source = db.get(CaseRoadArtifact, identifier)
        item = {'artifact_id': identifier, 'artifact_sha256': artifact['content_sha256'],
            'case_id': source.case_id, 'result_id': content['result_id'],
            'source_result_sha256': content['content_sha256'], 'map_snapshot_id': content['map_snapshot_id'],
            'network_id': calculation['network_id'], 'graph_sha256': calculation['graph_sha256'],
            'policy_revision': calculation['policy_revision'], 'analysis_at': calculation['analysis_at'],
            'engine_version': calculation.get('engine_version'),
            'vehicle': calculation['vehicle'], 'created_at': artifact['created_at'],
            'operation': 'route' if route is not None else 'comparison',
            'evidence_ref': f'road_artifact:{identifier}',
            'boundary': '历史留存的道路参考，不是实际轨迹或当前通行保证。',
            'information_gaps': content.get('information_gaps', [])[:10]}
        if route is not None:
            item.update(target=content.get('target'), distance_m=route.get('distance_m'),
                        detour_reference=route.get('detour_reference'),
                        alternative_count=len(route.get('alternatives', [])))
        else:
            # These targets and cells have already passed the same source and
            # passage reauthorization used by the report download service.
            item.update(targets=content.get('targets', [])[:20], cells=calculation.get('cells', [])[:20])
        items.append(item)
    more = len(ids) > args.page_size
    gaps = ['只读取已有留存成果，不自动重算；未有路径的案件不能据此判断不存在绕行。',
            '不同版本或同案多次计算可能同时出现，不将成果条数当成案件数。']
    if more or withheld:
        gaps.append('本批结果有读取上限或不可用引用，不能作为全库无关联的结论。')
    return {'items': items, 'returned': len(items), 'page': args.page,
            'next_page': args.page + 1 if more else None}, gaps, bool(more or withheld)


def validate_road_query_evidence(db, result):
    for card in (result or {}).get('cards', []):
        if card.get('tool') != 'find_road_results':
            continue
        for item in card.get('data', {}).get('items', []):
            try:
                current = read_road_artifact(db, item['artifact_id'])
                if current['content_sha256'] != item['artifact_sha256']:
                    raise ValueError('changed')
            except (ValueError, PermissionError, KeyError) as error:
                raise PermissionError('query_road_evidence_changed') from error
