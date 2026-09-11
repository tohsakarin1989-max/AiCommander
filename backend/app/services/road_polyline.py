"""Bounded geometry codec, independent of databases and application secrets."""


def decode_road_geometry(encoded):
    """Decode polyline6 into GeoJSON longitude/latitude pairs."""
    if not isinstance(encoded, str) or not 1 <= len(encoded) <= 2_000_000:
        raise ValueError('invalid_road_document_geometry')
    index = latitude = longitude = 0
    points = []

    def delta():
        nonlocal index
        value = shift = 0
        while True:
            if index >= len(encoded) or shift > 30:
                raise ValueError('invalid_road_document_geometry')
            byte = ord(encoded[index]) - 63
            index += 1
            if not 0 <= byte <= 63:
                raise ValueError('invalid_road_document_geometry')
            value += (byte & 31) * 2 ** shift
            if byte < 32:
                return -(value // 2 + 1) if value % 2 else value // 2
            shift += 5

    while index < len(encoded):
        latitude += delta()
        longitude += delta()
        if abs(latitude) > 85_000_000 or abs(longitude) > 180_000_000 or len(points) >= 100000:
            raise ValueError('invalid_road_document_geometry')
        points.append([longitude / 1e6, latitude / 1e6])
    if len(points) < 2:
        raise ValueError('invalid_road_document_geometry')
    return points
