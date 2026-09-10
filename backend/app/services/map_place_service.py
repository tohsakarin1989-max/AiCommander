"""Authorized snapshot-bound lookup in registered public gazetteers."""
import hashlib
import sqlite3
from typing import Any

from sqlalchemy.orm import Session

from app.models.map_foundation import MapPackageArtifact
from app.services.offline_map_service import OfflineMapService
from app.services.public_place_index import normalize, search_index


MAX_INDEX_BYTES = 64 * 1024 * 1024


def search_places(db: Session, snapshot_ref: str, query: str, *,
                  limit: int = 20, area_id: int | None = None) -> dict[str, Any]:
    """Recheck current scope even when an immutable historical ID is supplied."""
    snapshot = OfflineMapService.resolve_snapshot(db, snapshot_ref, area_id=area_id)
    if not 2 <= len(normalize(query)) <= 120 or not 1 <= limit <= 50:
        raise ValueError("invalid_place_query")
    artifacts = db.query(MapPackageArtifact).filter(
        MapPackageArtifact.public_bundle_id == snapshot.public_bundle_id,
        MapPackageArtifact.snapshot_id.is_(None),
        MapPackageArtifact.artifact_kind == "gazetteer",
    ).limit(2).all()
    if not artifacts:
        raise ValueError("place_index_not_configured")
    if len(artifacts) != 1:
        raise ValueError("place_index_unavailable")
    artifact = artifacts[0]
    try:
        if not 0 < artifact.size_bytes <= MAX_INDEX_BYTES:
            raise ValueError("invalid_index_size")
        path = OfflineMapService._storage_path(artifact.storage_key)
        with path.open("rb") as source:
            content = source.read(artifact.size_bytes + 1)
        if (len(content) != artifact.size_bytes
                or hashlib.sha256(content).hexdigest() != artifact.sha256):
            raise ValueError("index_checksum_mismatch")
        result = search_index(path, query, limit=limit, verified_content=content)
        # Only public provenance hashes leave the service, not arbitrary index
        # metadata (which can include build paths or diagnostic records).
        source = result.pop("source")
        if not isinstance(source, dict):
            raise ValueError("invalid_index_source")
        result["source"] = {
            key: value for key, value in source.items()
            if key in {"source_sha256", "region_sha256"}
            and isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value)
        }
    except (OSError, ValueError, sqlite3.Error, KeyError, TypeError) as exc:
        raise ValueError("place_index_unavailable") from exc
    return {**result, "snapshot_id": snapshot.id, "snapshot_version": snapshot.version,
            "index_sha256": artifact.sha256,
            "boundary": "公共地名参考点，不代表已核验入口、准确地址或可通行终点"}
