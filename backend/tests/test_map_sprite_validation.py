import io
import json

from PIL import Image
import pytest

from app.services.map_sprite_validation import validate_sprite_pair, validate_sprite_scales


def png(size=(8, 8), format='PNG'):
    output = io.BytesIO()
    Image.new('RGBA', size).save(output, format=format)
    return output.getvalue()


def index(**values):
    return json.dumps({'dot': {'x': 0, 'y': 0, 'width': 8, 'height': 8,
                              'pixelRatio': 1, **values}}).encode()


def test_valid_sprite_and_empty_unused_atlas():
    assert validate_sprite_pair(index(), png(), pixel_ratio=1) == {'dot'}
    assert validate_sprite_pair(b'{}', png((1, 1)), pixel_ratio=1) == set()


@pytest.mark.parametrize('content', [index(x=1), index(width=0), index(x=-1),
    index(pixelRatio=2), index(width=True), index(extra='unknown'),
    b'{"dot":{},"dot":{}}', b'[]', index(x=1e99)])
def test_invalid_geometry_and_json_rejected(content):
    with pytest.raises(ValueError):
        validate_sprite_pair(content, png(), pixel_ratio=1)


@pytest.mark.parametrize('image', [b'not image', png()[:-20], png(format='BMP'), png((4097, 1))])
def test_invalid_image_rejected(image):
    with pytest.raises(ValueError):
        validate_sprite_pair(index(), image, pixel_ratio=1)


def test_scales_must_describe_same_logical_icon():
    assert validate_sprite_scales(index(), png(), index(width=16, height=16, pixelRatio=2),
                                  png((16, 16))) == {'dot'}
    with pytest.raises(ValueError, match='sprite_scale_dimensions_mismatch'):
        validate_sprite_scales(index(), png(), index(pixelRatio=2), png())
