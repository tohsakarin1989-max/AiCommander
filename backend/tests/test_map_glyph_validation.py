"""Actual protobuf wire fixtures, not mocked decoder responses."""
import pytest

from app.services.map_glyph_validation import validate_glyph_range, inspect_glyph_range


def integer(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result + bytes([value]))


def field(number, value):
    if isinstance(value, int):
        return integer(number << 3) + integer(value)
    return integer((number << 3) | 2) + integer(len(value)) + value


def glyph(code=65, bitmap=b'\xff' * 49, width=1):
    return b''.join(field(k, v) for k, v in {
        1: code, 2: bitmap, 3: width, 4: 1, 5: 0, 6: 2, 7: 2}.items())


def stack(glyphs=(), name=b'Noto Sans CJK SC Regular', span=b'0-255'):
    return field(1, field(1, name) + field(2, span) + b''.join(field(3, g) for g in glyphs))


def test_valid_bitmap_and_metrics():
    assert validate_glyph_range(stack([glyph()]), '0-255') == {65}


def test_composite_payload_requires_exact_expected_fontstack():
    name = 'Noto Sans CJK SC Regular,Noto Sans Mongolian Regular,Noto Emoji Regular'
    content = stack([glyph(code=127973)], name=name.encode(), span=b'127744-127999')
    assert inspect_glyph_range(content, '127744-127999', fontstack=name)[0] == {127973}
    with pytest.raises(ValueError, match='glyph_stack_mismatch'):
        inspect_glyph_range(content, '127744-127999')
    with pytest.raises(ValueError):
        inspect_glyph_range(content, '127744-127999', fontstack='unknown')


@pytest.mark.parametrize('name', [None, [], {}, True])
def test_invalid_expected_fontstack_is_a_validation_error(name):
    with pytest.raises(ValueError, match='invalid_fontstack'):
        inspect_glyph_range(stack(), '0-255', fontstack=name)


@pytest.mark.parametrize('start,code', [(65536, 65536), (127744, 127973), (1113856, 1114111)])
def test_supplementary_unicode_ranges_decode(start, code):
    span = f'{start}-{start + 255}'
    assert validate_glyph_range(stack([glyph(code=code)], span=span.encode()), span) == {code}


@pytest.mark.parametrize('span', ['1114112-1114367', '127745-128000', '0127744-127999'])
def test_out_of_unicode_or_noncanonical_ranges_fail(span):
    with pytest.raises(ValueError):
        validate_glyph_range(stack(span=span.encode()), span)


def test_empty_range_is_valid_not_complete_character_coverage():
    assert validate_glyph_range(stack(), '0-255') == set()


def test_space_can_omit_bitmap():
    space = b''.join(field(k, v) for k, v in {1: 32, 3: 0, 4: 0, 5: 0, 6: 0, 7: 6}.items())
    assert validate_glyph_range(stack([space]), '0-255') == {32}


def test_blank_nonspace_id_is_not_drawable():
    blank = b''.join(field(k, v) for k, v in {1: 65, 3: 0, 4: 0, 5: 0, 6: 0, 7: 6}.items())
    ids, drawable = inspect_glyph_range(stack([blank]), '0-255')
    assert ids == {65}
    assert drawable == set()


@pytest.mark.parametrize('content', [
    b'', b'not protobuf', b'\x80' * 12, b'\x0a\xff\x7f',
    stack([glyph(bitmap=b'x')]), stack([glyph(code=256)]),
    stack([glyph(), glyph()]), stack([glyph(width=4096)]),
    stack([field(1, 65)]), stack(name=b'other'), stack(span=b'256-511'),
    stack() + stack(), stack([glyph() + field(1, 65)]),
    stack([glyph() + field(8, 1)]), field(1, field(1, b'\xff') + field(2, b'0-255')),
], ids=['empty', 'text', 'varint', 'truncated', 'bitmap', 'outside', 'duplicate',
        'dimensions', 'metrics', 'font', 'range', 'stacks', 'field_duplicate', 'unknown', 'utf8'])
def test_invalid_glyph_payload_rejected(content):
    with pytest.raises(ValueError):
        validate_glyph_range(content, '0-255')


@pytest.mark.parametrize('span', ['1-256', '0-256', '00-255', '1114112-1114367', '../0-255'])
def test_invalid_range_contract(span):
    with pytest.raises(ValueError):
        validate_glyph_range(stack(), span)
