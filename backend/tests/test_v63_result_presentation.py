"""Frozen v6.3 process and conditions survive document projection unchanged."""
from copy import deepcopy
from io import BytesIO

from zipfile import ZipFile

from app.services.case_process_document import condition_blocks
from app.services.case_result_document import build_case_result_document
from app.services.case_result_export import render_docx
from app.services.case_result_snapshot import assemble_case_result
from app.services.case_semantic_service import build_semantic_profile
from tests.test_case_result_snapshot import inputs


def test_nonaffirmed_process_export_keeps_source_and_does_not_invent_measurement_fact():
    profile, _, _ = inputs()
    profile.payload['semantics'] = build_semantic_profile({'description': '未转运原油120升。从东井场转运至西村屯。'})
    frozen = {'id': 'synthetic-process', **assemble_case_result(profile, None, [])}
    before = deepcopy(frozen)
    document = build_case_result_document(frozen)
    text = '\n'.join(block.text for block in document.blocks)
    assert '120.0 升（不确定）' in text
    assert '同句涉及' in text
    assert '原文来源：东井场' in text and '原文去向：西村屯' in text
    assert '阶段未知' in text
    with ZipFile(BytesIO(render_docx(document))) as output:
        contents = output.read('word/document.xml').decode()
    assert '原文计量' in contents and '不确定' in contents and '原文否定' in contents
    assert before == frozen


def test_all_pool_conditions_and_real_change_refs_are_exported_without_new_calculation():
    comparison = {'schema_version': 'facility-conditions-6.3-1', 'boundary': '不确认来源', 'priority_gaps': [],
        'rows': [{'asset_id': 99, 'name': '合成未排名设施', 'boundary': '未知不按不符',
            'source_context': {'valid_at': None, 'known_at': '2026-09-27', 'version_id': None},
            'conditions': [{'key': 'road', 'label': '道路', 'state': 'unknown', 'reason': '未取得路径',
                'evidence_refs': ['map_asset:99@snapshot:synthetic'], 'dependencies': ['可信入口']}]}]}
    change = {'state': 'compared', 'baseline': None, 'boundary': '不做单因果推断', 'context_changes': ['network'],
        'changes': [{'asset_id': 99, 'name': '合成未排名设施', 'previous_rank': 3, 'current_rank': None,
            'reasons': ['本轮未完成'], 'changed_conditions': [{'key': 'road', 'previous_state': 'supported',
                'current_state': 'unknown', 'evidence_refs': ['road-v2']}]}]}
    blocks = condition_blocks(comparison, change)
    text = '\n'.join(block.text for block in blocks)
    for phrase in ('合成未排名设施', '资料未知', '可信入口', 'road-v2', '不做单因果推断', 'network'):
        assert phrase in text


def test_export_keeps_time_precision_and_uncertain_relationship():
    profile, _, _ = inputs()
    profile.payload['semantics'] = build_semantic_profile({'description':
        '先未抽取原油，随后转运。2026年9月20日23时至2026年9月21日1时抽取原油。'})
    process = profile.payload['semantics']['process']
    assert process['relations'][0]['kind'] == 'uncertain'
    assert any(event['time_intervals'] for event in process['events'])
    document = build_case_result_document({'id': 'synthetic-precision', **assemble_case_result(profile, None, [])})
    text = '\n'.join(block.text for block in document.blocks)
    assert '23:00（小时精度）' in text
    assert '01:00（小时精度' in text
    assert '原文明示先后表述（不确定）' in text
