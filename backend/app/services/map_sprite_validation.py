"""Decode bounded offline sprite atlases and bind each icon to its real pixels."""
import io

from PIL import Image, UnidentifiedImageError

from app.services.map_style_dependencies import _load


def validate_sprite_pair(index_content: bytes, png_content: bytes, *, pixel_ratio: int) -> set[str]:
    """Fixed 1x/2x, non-SDF atlas profile; extended sprite formats are rejected."""
    if (type(pixel_ratio) is not int or pixel_ratio not in (1, 2)
            or not isinstance(png_content, bytes) or not 0 < len(png_content) <= 16 * 1024 * 1024):
        raise ValueError('invalid_sprite_contract')
    index = _load(index_content)
    if len(index) > 4096:
        raise ValueError('too_many_sprite_icons')
    try:
        with Image.open(io.BytesIO(png_content)) as image:
            if (image.format != 'PNG' or getattr(image, 'n_frames', 1) != 1
                    or not 0 < image.width <= 4096 or not 0 < image.height <= 4096):
                raise ValueError('invalid_sprite_image')
            width, height = image.size
            image.verify()
        # verify checks structure/CRC; load separately exercises actual decoding.
        with Image.open(io.BytesIO(png_content)) as image:
            image.load()
    except (OSError, UnidentifiedImageError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError('invalid_sprite_image') from exc
    fields = {'x', 'y', 'width', 'height', 'pixelRatio'}
    for name, record in index.items():
        if (not isinstance(name, str) or not 1 <= len(name) <= 100
                or any(ord(c) < 32 for c in name)
                or not isinstance(record, dict) or set(record) != fields
                or any(type(record[k]) is not int for k in fields)
                or record['pixelRatio'] != pixel_ratio
                or min(record['x'], record['y']) < 0
                or min(record['width'], record['height']) <= 0
                or record['x'] + record['width'] > width
                or record['y'] + record['height'] > height):
            raise ValueError('invalid_sprite_geometry')
    return set(index)


def validate_sprite_scales(index1: bytes, png1: bytes, index2: bytes, png2: bytes) -> set[str]:
    names = validate_sprite_pair(index1, png1, pixel_ratio=1)
    if names != validate_sprite_pair(index2, png2, pixel_ratio=2):
        raise ValueError('sprite_scale_icon_mismatch')
    first, second = _load(index1), _load(index2)
    if any(second[name][axis] != first[name][axis] * 2
           for name in names for axis in ('width', 'height')):
        raise ValueError('sprite_scale_dimensions_mismatch')
    return names
