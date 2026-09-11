import pytest

from app.models.internal_roads import InternalRoadImport
from app.models.road_public_alias import RoadPublicAlias
from app.services.road_public_alias_service import AliasDecision, record_alias_decision, current_aliases
from test_map_foundation import db_session  # noqa: F401
from test_internal_road_import import source  # noqa: F401
from test_road_build_inputs import prepared  # noqa: F401


def decision(batch_id, **changes):
    return AliasDecision(**{'import_id': batch_id, 'feature_id': 'road-1', 'public_source_sha256': 'a' * 64,
        'osm_way_id': 12345678901, 'decision': 'verified', 'request_key': 'alias-1',
        'evidence_reference': '合成整段对应核验', **changes})


def read(db, batch_id, **changes):
    return current_aliases(db, **{'import_id': batch_id, 'feature_id': 'road-1',
                                 'public_source_sha256': 'a' * 64, **changes})


def test_alias_is_idempotent_and_exact_version_bound(prepared):
    db, _, batch_id = prepared
    original = db.get(InternalRoadImport, batch_id).input_sha256
    row, created = record_alias_decision(db, decision(batch_id))
    assert created
    same, created = record_alias_decision(db, decision(batch_id))
    assert not created and same.id == row.id
    assert [entry.id for entry in read(db, batch_id)] == [row.id]
    assert read(db, batch_id, public_source_sha256='b' * 64) == []
    assert read(db, batch_id + 1) == []
    assert db.get(InternalRoadImport, batch_id).input_sha256 == original


def test_revocation_and_stale_update_do_not_restore_correspondence(prepared):
    db, _, batch_id = prepared
    row, _ = record_alias_decision(db, decision(batch_id))
    revoked, _ = record_alias_decision(db, decision(batch_id, decision='revoked', request_key='alias-2', previous_id=row.id))
    assert read(db, batch_id) == []
    with pytest.raises(ValueError, match='review_changed'):
        record_alias_decision(db, decision(batch_id, request_key='alias-3', previous_id=row.id))
    assert revoked.sequence == 2
    with pytest.raises(ValueError, match='request_conflict'):
        record_alias_decision(db, decision(batch_id, osm_way_id=42))


def test_read_scope_and_missing_write_context_fail_closed(prepared):
    db, _, batch_id = prepared
    record_alias_decision(db, decision(batch_id))
    db.info['authorized_area_ids'] = ()
    assert read(db, batch_id) == []
    assert db.query(RoadPublicAlias).count() == 0
    with pytest.raises(LookupError):
        record_alias_decision(db, decision(batch_id, request_key='alias-other'))
    db.info['authorized_area_ids'] = (1,)
    db.info.pop('area_access_levels')
    with pytest.raises(PermissionError):
        record_alias_decision(db, decision(batch_id, request_key='alias-other'))
