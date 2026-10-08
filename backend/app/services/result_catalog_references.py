"""Extract explicit object pointers, never inferred names or copied fact text.

This index is deliberately not an exhaustive authorization manifest. The original
typed source validators remain mandatory, including for unrecognized old shapes.
"""
import re

FIELD_KINDS = {
    'case_id': 'case', 'source_case_id': 'case', 'case_ids': 'case',
    'profile_id': 'case_profile', 'case_profile_id': 'case_profile', 'profile_case_ids': 'case',
    'asset_id': 'asset', 'asset_ids': 'asset', 'source_revision_id': 'case_revision',
    'map_snapshot_id': 'map_snapshot', 'source_claim_id': 'map_claim', 'source_claim_ids': 'map_claim',
    'asset_version_ids': 'asset_version', 'supporting_version_ids': 'asset_version',
    'source_identity_id': 'facility_identity', 'identity_decision_id': 'facility_identity_decision',
    'analysis_run_id': 'case_analysis_run', 'event_id': 'event', 'topic_id': 'topic',
    'road_artifact_id': 'road_artifact', 'base_result_id': 'case_result',
    'parent_query_id': 'query',
}
MANIFEST_KINDS = {'cases': 'case', 'events': 'event', 'assets': 'asset',
                  'map_sources': 'map_source', 'maps': 'map_snapshot', 'road_imports': 'road_import'}
MATERIAL_KINDS = {'case': 'case_result', 'topic': 'topic_snapshot', 'facility': 'facility_material',
                  'query': 'query', 'situation': 'situation', 'meeting': 'report',
                  'experience': 'knowledge_asset', 'conclusion': 'conclusion'}
TEXT_KINDS = {'case', 'case_profile', 'case_result', 'case_revision', 'case_hypothesis',
              'road_artifact', 'report', 'map_snapshot', 'map_source', 'asset_version',
              'map_claim', 'map_field_decision', 'facility_identity', 'facility_identity_decision',
              'tech_aggregate', 'knowledge_asset', 'internal_road_import', 'road_import'}


def extract_references(kind, row, state):
    found = set()

    def add(ref_kind, identifier, version=None, relation='source'):
        if identifier is None or isinstance(identifier, (dict, list, bool)):
            return
        identifier, version = str(identifier), '' if version is None else str(version)
        if not identifier or len(identifier) > 120 or len(version) > 128:
            raise ValueError('catalog_reference_invalid')
        found.add((ref_kind, identifier, version, relation))

    def evidence(value):
        if not isinstance(value, str):
            return
        if match := re.fullmatch(r'business_result:([a-z_]+):([A-Za-z0-9_-]+)', value):
            if match[1] in MATERIAL_KINDS:
                add(MATERIAL_KINDS[match[1]], match[2], relation='evidence')
        elif match := re.fullmatch(r'map_asset:([0-9]+)@snapshot:([^:]+)', value):
            add('asset', match[1], relation='evidence')
            add('map_snapshot', match[2], relation='evidence')
        elif match := re.fullmatch(r'internal_road_entrance:([^:]+):(.+)', value):
            add('road_import', match[1], relation='evidence')
        elif match := re.fullmatch(r'([a-z_]+):([A-Za-z0-9_-]+)', value):
            if match[1] in TEXT_KINDS:
                add('road_import' if match[1] == 'internal_road_import' else match[1], match[2], relation='evidence')

    def walk(value):
        if isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            if value.get('kind') in MATERIAL_KINDS and {'id', 'content_sha256', 'schema_version'} <= value.keys():
                add(MATERIAL_KINDS[value['kind']], value['id'], value['content_sha256'], 'frozen_version')
            if value.get('source_type') in {'case', 'experience_card', 'legacy_experience_card'}:
                ref_kind = 'knowledge_asset' if value['source_type'] == 'experience_card' else 'case'
                add(ref_kind, value.get('source_id'), relation='history')
            for key, item in value.items():
                if key == 'reused_experience' and isinstance(item, list):
                    for ref in item:
                        if isinstance(ref, dict):
                            add('knowledge_asset', ref.get('asset_id'), ref.get('version'), 'reuse')
                            # This asset_id is a knowledge card, not a facility.
                            walk({name: content for name, content in ref.items() if name != 'asset_id'})
                    continue
                if key in FIELD_KINDS:
                    for identifier in item if isinstance(item, list) else [item]:
                        add(FIELD_KINDS[key], identifier)
                if key in {'evidence_refs', 'evidence_ref'}:
                    for ref in item if isinstance(item, list) else [item]:
                        evidence(ref)
                if key in {'source_manifest', 'facility_sources'} and isinstance(item, dict):
                    for name, ref_kind in MANIFEST_KINDS.items():
                        for identifier in item.get(name, []):
                            add(ref_kind, identifier, relation='population')
                if key == 'map_manifest_hashes' and isinstance(item, dict):
                    for identifier, digest in item.items():
                        add('map_snapshot', identifier, digest, 'frozen_version')
                if key == 'source_result' and isinstance(item, dict):
                    add('case_result', item.get('result_id'), item.get('content_sha256'), 'frozen_version')
                if key == 'frozen_result' and isinstance(item, dict):
                    add('case_result', item.get('id'), item.get('content_sha256'), 'frozen_version')
                if key == 'sources' and isinstance(item, list):
                    for ref in item:
                        if isinstance(ref, dict) and ref.get('kind') in MATERIAL_KINDS:
                            add(MATERIAL_KINDS[ref['kind']], ref.get('id'), ref.get('content_sha256'), 'frozen_version')
                walk(item)

    walk(state)
    if kind == 'case':
        composition = row.content.get('composition') or {}
        add('case_result', composition.get('base_result_id'), composition.get('base_content_sha256'), 'frozen_version')
        add('road_artifact', composition.get('road_artifact_id'), composition.get('road_content_sha256'), 'frozen_version')
    if kind == 'topic':
        for name, ref_kind in (('case_results', 'case_result'), ('roads', 'road_artifact'),
                               ('briefs', 'situation'), ('maps', 'map_snapshot')):
            for ref in (row.payload.get('references') or {}).get(name, []):
                add(ref_kind, ref['id'], ref.get('content_sha256') or ref.get('manifest_sha256'), 'frozen_version')
        for key in ('added_case_ids', 'removed_case_ids', 'updated_case_ids', 'entered_group', 'left_group'):
            for identifier in (row.changes or {}).get(key, []):
                add('case', identifier, relation='changes')
        for source in (row.payload.get('aggregate') or {}).get('source_manifest', []):
            add('case_profile', source.get('profile_id'), source.get('profile_content_sha256'), 'frozen_version')
        context = (row.payload.get('definition') or {}).get('source_context') or {}
        if context.get('kind') in {'case', 'facility'}:
            add('case' if context['kind'] == 'case' else 'asset', context.get('id'), relation='context')
    if kind in {'meeting', 'conclusion'}:
        add('meeting', row.meeting_id)
    return [{'reference_kind': key, 'reference_id': identifier,
             'expected_version': version, 'relation': relation}
            for key, identifier, version, relation in sorted(found)]
