import json

import pytest

from app.services.map_label_contract import label_contract


def content(expressions):
    return json.dumps({'layers': [{'type': 'symbol', 'source-layer': layer,
        'layout': {'text-field': value}} for layer, value in expressions]}).encode()


def test_extracts_actual_style_layers_and_coalesce_order():
    fields, literals = label_contract(content([
        ('road', ['coalesce', ['get', 'name:zh'], ['get', 'name'], '']),
        ('poi', ['get', 'ref']), ('place', '大庆'),
    ]))
    assert fields == {'road': ('name:zh', 'name'), 'poi': ('ref',)}
    assert literals == {ord('大'), ord('庆')}


@pytest.mark.parametrize('expression', [
    ['upcase', ['get', 'name']], ['concat', ['get', 'a'], ['get', 'b']],
    '{name}', ['get', 'name', ['properties']], ['coalesce', ['get', 'name'], '未知'],
])
def test_unanalysed_text_expression_cannot_claim_coverage(expression):
    with pytest.raises(ValueError, match='unsupported_label'):
        label_contract(content([('place', expression)]))


def test_distinct_expressions_on_same_source_need_separate_audit():
    with pytest.raises(ValueError, match='ambiguous_label'):
        label_contract(content([('place', ['get', 'name']), ('place', ['get', 'ref'])]))


def test_repeated_expression_and_no_text():
    assert label_contract(content([('place', ['get', 'name'])] * 2))[0] == {'place': ('name',)}
    assert label_contract(b'{"layers":[]}') == ({}, set())
    assert label_contract(b'{"layers":[{"type":"background"}]}') == ({}, set())


@pytest.mark.parametrize('style', [{'layers': None}, {'layers': [None]},
    {'layers': [{'layout': []}]}, {'layers': [{'type': 'symbol', 'source-layer': 'place',
        'layout': {'text-field': ['get', 'name'], 'text-transform': 'uppercase'}}]}])
def test_invalid_or_transforming_style_fails_closed(style):
    with pytest.raises(ValueError, match='unsupported_label'):
        label_contract(json.dumps(style).encode())
