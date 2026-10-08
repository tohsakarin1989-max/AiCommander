"""Current access to every recorded source in a mixed facility snapshot."""
from app.models.map_foundation import MapSource


def attributes_sources_visible(db, attributes, area_id):
    if not isinstance(attributes, dict):
        return False
    identifiers = []
    if attributes.get("source_id") is not None:
        identifiers.append(attributes["source_id"])
    groups = attributes.get("field_groups") or {}
    if not isinstance(groups, dict):
        return False
    for metadata in groups.values():
        if not isinstance(metadata, dict):
            return False
        if metadata.get("source_id") is not None:
            identifiers.append(metadata["source_id"])
    if any(type(value) is not int or value < 1 for value in identifiers):
        return False
    sources = set(identifiers)
    visible = {row[0] for row in db.query(MapSource.id).filter(
        MapSource.id.in_(sources), MapSource.status == "active", MapSource.operational_area_id == area_id,
    )} if sources else set()
    return sources == visible
