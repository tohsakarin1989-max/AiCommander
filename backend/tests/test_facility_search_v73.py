"""Synthetic facility search: current authorization precedes matching and paging."""
import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.models.jurisdiction import JurisdictionAsset
from app.models.user import User
from app.models.map_foundation import (
    FacilityIdentityDecision, FacilitySourceIdentity, JurisdictionAssetVersion,
    MapSource, OperationalArea,
)
from app.services.jurisdiction_service import JurisdictionService
from app.services.intelligent_query_tools import FindPlaces, _places


@pytest.fixture
def search(db_session):
    return seed_search(db_session)


def seed_search(db):
    db.add_all([OperationalArea(id=n, code=f"area-{n}", name=f"厂区{n}") for n in (1, 2)])
    db.add(User(id=1, username="synthetic-search", display_name="合成用户", password_hash="unused", role="admin"))
    db.flush()
    db.add_all([MapSource(id=n, source_key=f"source-{n}", name=f"来源{n}",
                          source_type="production", operational_area_id=1 if n < 3 else 2)
                for n in (1, 2, 3)])
    db.commit()
    db.info["authorized_area_ids"] = (1,)
    return db


def asset(db, name="当前井名", **kwargs):
    item = JurisdictionAsset(name=name, asset_type="well", operational_area_id=1, **kwargs)
    db.add(item)
    db.flush()
    return item


def historical(db, item, name, *, number=1, source_id=1, **kwargs):
    version = JurisdictionAssetVersion(asset_id=item.id, version=number,
        snapshot={"name": name, "operational_area_id": item.operational_area_id,
                  "attributes": {"source_id": source_id}}, change_type="update", **kwargs)
    db.add(version)
    db.flush()
    return version


def identity(db, item, name="旧台账编号", source_id=1):
    row = FacilitySourceIdentity(source_id=source_id, operational_area_id=1,
        native_asset_id=item.id, identity_key=name, source_record_id=name,
        asset_type="well", identity_kind="exact_id")
    db.add(row)
    db.flush()
    return row


def find(db, word, **kwargs):
    return JurisdictionService.list_assets(db, keyword=word, **kwargs)


@pytest.mark.parametrize("word,kind", [("当前", "current_name"), ("EXT-7", "external_id"),
                                     ("北侧入口", "address")])
def test_normal_and_assistant_search_share_current_fields_and_paging(search, word, kind):
    first = asset(search, external_id="EXT-7", address="北侧入口")
    second = asset(search, external_id="EXT-7", address="北侧入口")
    for n in range(70):
        asset(search, f"无关井{n}")
    search.commit()
    assert [row.id for row in find(search, word, limit=1)] == [second.id]
    assert [row.id for row in find(search, word, limit=1, skip=1)] == [first.id]
    result, _ = _places(search, FindPlaces(keyword=word, limit=1, offset=1))
    assert result["total"] == 2
    assert result["items"][0]["id"] == first.id
    assert result["items"][0]["search_match"] == {"kind": kind, "value": getattr(first, {
        "current_name": "name", "external_id": "external_id", "address": "address"}[kind])}


def test_early_historical_name_and_explicit_source_id_have_labels(search):
    item = asset(search)
    version = historical(search, item, "早期旧井名")
    historical(search, item, "最近井名", number=2)
    alias = identity(search, item)
    search.commit()
    match = find(search, "早期旧")[0].search_match
    assert match == {"kind": "historical_name", "value": "早期旧井名", "version_id": version.id}
    assert find(search, "旧台账")[0].search_match == {"kind": "source_alias", "value": "旧台账编号",
        "identity_id": alias.id, "source_id": 1}
    # Never merge equal names or alias text into an identity.
    other = asset(search)
    search.commit()
    assert {row.id for row in find(search, "当前井名")} == {item.id, other.id}
    assert [row.id for row in find(search, "旧台账")] == [item.id]


def test_revoked_scope_source_and_mixed_sources_are_filtered_before_count(search):
    visible = asset(search, "共同名称", attributes={"source_id": 1})
    revoked = asset(search, "共同名称", attributes={"source_id": 2})
    mixed = asset(search, "共同名称", attributes={"source_id": 1,
        "field_groups": {"production": {"source_id": 2}}})
    foreign = asset(search, "共同名称", attributes={"field_groups": {"identity": {"source_id": 3}}})
    search.query(MapSource).filter_by(id=2).update({"status": "inactive"})
    search.commit()
    assert [row.id for row in find(search, "共同", limit=1)] == [visible.id]
    result, _ = _places(search, FindPlaces(keyword="共同"))
    assert result["total"] == 1
    assert {row["id"] for row in result["items"]}.isdisjoint({revoked.id, mixed.id, foreign.id})
    search.info["authorized_area_ids"] = ()
    assert find(search, "共同") == []
    assert _places(search, FindPlaces(keyword="共同"))[0]["total"] == 0


def test_history_and_alias_stop_matching_after_source_revocation(search):
    item = asset(search)
    historical(search, item, "旧名称")
    identity(search, item)
    search.commit()
    assert find(search, "旧名称") and find(search, "旧台账")
    search.query(MapSource).filter_by(id=1).update({"status": "inactive"})
    search.commit()
    assert find(search, "旧名称") == []
    assert find(search, "旧台账") == []
    assert [row.id for row in find(search, "当前")] == [item.id]


def test_historical_mixed_cross_area_sources_and_revoked_identity_are_not_aliases(search):
    item = asset(search)
    alias = identity(search, item)
    version = historical(search, item, "绑定时旧名", source_identity_id=alias.id)
    historical(search, item, "跨区旧名", number=2, source_id=3)
    mixed = historical(search, item, "混合旧名", number=3)
    mixed.snapshot = {**mixed.snapshot, "attributes": {"source_id": 1,
        "field_groups": {"coordinates": {"source_id": 3}}}}
    search.commit()
    assert find(search, "跨区旧名") == []
    assert find(search, "混合旧名") == []
    assert find(search, "绑定时旧名")[0].search_match["version_id"] == version.id
    search.add(FacilityIdentityDecision(identity_id=alias.id, operational_area_id=1,
        target_asset_id=item.id, sequence=1, action="revoke", actor_id=1, note="撤销", request_key="revoked"))
    search.commit()
    assert find(search, "绑定时旧名") == []


def test_scope_and_inactive_assets_are_filtered_before_assistant_count(search):
    expected = asset(search, "同名")
    asset(search, "同名", status="inactive")
    search.add(JurisdictionAsset(name="同名", asset_type="well", operational_area_id=2))
    search.commit()
    assert [row.id for row in find(search, "同名")] == [expected.id]
    assert _places(search, FindPlaces(keyword="同名"))[0]["total"] == 1
    assert find(search, "同名", operational_area_id=2) == []
    assert len(find(search, "同名", status=None)) == 2  # Existing explicit status override.


def test_latest_binding_controls_alias_and_revocation_never_falls_back(search):
    original = asset(search, "原井")
    target = asset(search, "目标井")
    alias = identity(search, original)
    search.add(FacilityIdentityDecision(identity_id=alias.id, operational_area_id=1,
        target_asset_id=target.id, sequence=1, action="bind", actor_id=1, note="确认", request_key="one"))
    search.commit()
    assert [row.id for row in find(search, "旧台账")] == [target.id]
    search.add(FacilityIdentityDecision(identity_id=alias.id, operational_area_id=1,
        target_asset_id=target.id, sequence=2, action="revoke", actor_id=1, note="撤销", request_key="two"))
    search.commit()
    assert find(search, "旧台账") == []


@pytest.mark.parametrize("attrs", [{"source_id": True}, {"source_id": "1"},
    {"source_id": 1.5}, {"source_id": 0}, {"field_groups": "bad"},
    {"field_groups": {"identity": "bad"}}, {"field_groups": {"identity": {"source_id": False}}}])
def test_malformed_source_provenance_fails_closed_without_sql_error(search, attrs):
    asset(search, attributes=attrs)
    search.commit()
    assert find(search, "当前") == []


@pytest.mark.parametrize("word", ["%", "_", "\\", "' OR 1=1 --"])
def test_literal_keyword_not_wildcard(search, word):
    expected = asset(search, f"字{word}字")
    asset(search, "其他")
    search.commit()
    assert [row.id for row in find(search, word)] == [expected.id]


def test_empty_and_database_failure_are_not_confused(search, monkeypatch):
    assert find(search, "无结果") == []
    with pytest.raises(ValidationError):
        FindPlaces(keyword="   ")
    def broken(*_args, **_kwargs):
        raise OperationalError("synthetic failure", {}, Exception("offline"))
    monkeypatch.setattr(search, "execute", broken)
    with pytest.raises(OperationalError):
        find(search, "无结果")
