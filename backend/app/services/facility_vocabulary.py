"""Small reviewed lexical vocabulary; no fuzzy identity or unit conversion."""
VERSION = 'facility-vocabulary-9.2-1'
TERMS = {
    'asset_type': {'well': ('well', '井', '油井'), 'station': ('station', '站库'),
                   'pipeline': ('pipeline', '管线'), 'road': ('road', '道路')},
    'oil_type': {'crude_oil': ('原油', 'crude_oil'), 'diesel': ('柴油', 'diesel'),
                 'gasoline': ('汽油', 'gasoline')},
    'production_output_unit': {'tonne': ('吨', 't'), 'cubic_metre': ('立方米', 'm³', 'm3')},
    'water_cut_unit': {'percent': ('%', 'percent', '百分比')},
    'production_period': {'day': ('日', '每日', '天'), 'month': ('月', '每月')},
    'production_status': {'operating': ('生产', '在产'), 'stopped': ('停产',)},
}


def describe(values):
    result = {}
    for field, codes in TERMS.items():
        raw = values.get(field)
        if raw in (None, ''):
            continue
        text = str(raw).strip()
        code = next((key for key, aliases in codes.items() if text in aliases), None)
        result[field] = {'raw': raw, 'code': code, 'state': 'mapped' if code else 'unmapped',
                         'basis': 'reviewed_exact_alias' if code else 'original_value_only',
                         'vocabulary_version': VERSION}
    return result
