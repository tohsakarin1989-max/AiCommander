"""Extract auditable labels, not an evaluator for arbitrary style expressions.

Supports the shipped get/coalesce label contract and fixed plain strings.
Other expressions must acquire an equivalent audit before they can be imported.
Visibility/zoom filters are deliberately ignored: coverage is conservative.
"""
from app.services.map_style_dependencies import _load


def _field(value):
    if (isinstance(value, list) and len(value) == 2 and value[0] == 'get'
            and isinstance(value[1], str) and 1 <= len(value[1]) <= 128):
        return value[1]
    raise ValueError('unsupported_label_expression')


def label_contract(content: bytes) -> tuple[dict[str, tuple[str, ...]], set[int]]:
    """Use only alongside full style validation; no public expression input."""
    fields, literals = {}, set()
    layers = _load(content).get('layers', [])
    if not isinstance(layers, list) or len(layers) > 128:
        raise ValueError('unsupported_label_layers')
    for layer in layers:
        if not isinstance(layer, dict):
            raise ValueError('unsupported_label_layer')
        layout = layer.get('layout', {})
        if not isinstance(layout, dict):
            raise ValueError('unsupported_label_layout')
        if 'text-field' not in layout:
            continue
        if (layer.get('type') != 'symbol' or not isinstance(layer.get('source-layer'), str)
                or layout.get('text-transform', 'none') != 'none'):
            raise ValueError('unsupported_label_layer')
        value = layout['text-field']
        if isinstance(value, str):
            if len(value) > 4096 or '{' in value or '}' in value:
                raise ValueError('unsupported_label_template')
            literals.update(ord(char) for char in value if not char.isspace())
            continue
        if isinstance(value, list) and value and value[0] == 'coalesce':
            if not 3 <= len(value) <= 18 or value[-1] != '':
                raise ValueError('unsupported_label_coalesce')
            chain = tuple(_field(item) for item in value[1:-1])
        else:
            chain = (_field(value),)
        name = layer['source-layer']
        if name in fields and fields[name] != chain:
            raise ValueError('ambiguous_label_expressions')
        fields[name] = chain
    return fields, literals
