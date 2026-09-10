"""Bounded glyph PBF validation for the fixed offline font, without GIS imports.

Protocol: mapbox/fontnik proto/glyphs.proto; SDF border is three pixels, as in
the installed MapLibre parse_glyph_pbf.ts. This does not prove font coverage.
"""
import re
from app.services.map_font_profiles import validate_fontstack


FONT = 'Noto Sans CJK SC Regular'
MAX_BYTES = 2 * 1024 * 1024


def parse_glyph_range(range_name: str) -> tuple[int, int]:
    """Canonical 256-codepoint block within Unicode, not arbitrary integers."""
    if not isinstance(range_name, str) or not re.fullmatch(
            r'(0|[1-9][0-9]{0,6})-([1-9][0-9]{0,6})', range_name):
        raise ValueError('invalid_glyph_contract')
    start, end = map(int, range_name.split('-'))
    if start % 256 or end != start + 255 or end > 0x10ffff:
        raise ValueError('invalid_glyph_contract')
    return start, end


def glyph_asset_range(name: str) -> str:
    if not isinstance(name, str) or not name.startswith('glyphs-') or not name.endswith('.pbf'):
        raise ValueError('invalid_glyph_asset_name')
    span = name[7:-4]
    parse_glyph_range(span)
    return span


def _varint(data: bytes, offset: int) -> tuple[int, int]:
    result = 0
    for shift in range(0, 35, 7):
        if offset >= len(data):
            break
        value = data[offset]
        offset += 1
        result |= (value & 127) << shift
        if not value & 128:
            if result > 0xffffffff:
                break
            return result, offset
    raise ValueError('invalid_glyph_varint')


def _fields(data: bytes, schema: dict[int, int], repeated: int | None = None):
    result = {}
    offset = 0
    while offset < len(data):
        tag, offset = _varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if number not in schema or wire != schema[number]:
            raise ValueError('invalid_glyph_field')
        value, offset = _varint(data, offset)
        if wire == 2:
            end = offset + value
            if end > len(data):
                raise ValueError('truncated_glyph_field')
            value, offset = data[offset:end], end
        if number == repeated:
            items = result.setdefault(number, [])
            if len(items) >= 256:
                raise ValueError('too_many_glyphs')
            items.append(value)
        elif number in result:
            raise ValueError('duplicate_glyph_field')
        else:
            result[number] = value
    return result


def inspect_glyph_range(content: bytes, range_name: str, *, fontstack: str = FONT) -> tuple[set[int], set[int]]:
    """Return all IDs and nonempty drawable IDs, not semantic glyph identity."""
    if not isinstance(content, bytes) or not 0 < len(content) <= MAX_BYTES:
        raise ValueError('invalid_glyph_contract')
    start, end = parse_glyph_range(range_name)
    validate_fontstack(fontstack)
    root = _fields(content, {1: 2})
    if set(root) != {1}:
        raise ValueError('invalid_glyph_stack')
    stack = _fields(root[1], {1: 2, 2: 2, 3: 2}, repeated=3)
    if stack.get(1) != fontstack.encode() or stack.get(2) != range_name.encode():
        raise ValueError('glyph_stack_mismatch')
    ids, drawable = set(), set()
    for encoded in stack.get(3, []):
        glyph = _fields(encoded, {1: 0, 2: 2, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0})
        if not {1, 3, 4, 5, 6, 7} <= glyph.keys():
            raise ValueError('missing_glyph_metrics')
        code, width, height = glyph[1], glyph[3], glyph[4]
        if (not start <= code <= end or code in ids or width > 256 or height > 256
                or glyph[7] > 512):
            raise ValueError('invalid_glyph_metrics')
        # A signed metric is zigzag encoded. Fixed 24px generated fonts do not
        # require extreme offsets; bound both signs before rendering.
        if any(abs((glyph[k] >> 1) ^ -(glyph[k] & 1)) > 512 for k in (5, 6)):
            raise ValueError('invalid_glyph_offset')
        bitmap = glyph.get(2)
        if bitmap is not None and len(bitmap) != (width + 6) * (height + 6):
            raise ValueError('invalid_glyph_bitmap')
        if bitmap is None and (width or height):
            raise ValueError('missing_glyph_bitmap')
        ids.add(code)
        # Fixed MapLibre SDF inner edge is 0.75. A nonzero byte may still be
        # fully transparent; require an ink sample above that edge (192/255).
        if width and height and bitmap and max(bitmap) >= 192:
            drawable.add(code)
    return ids, drawable


def validate_glyph_range(content: bytes, range_name: str) -> set[int]:
    """Return decoded IDs; presence alone is not evidence of visible coverage."""
    return inspect_glyph_range(content, range_name)[0]
