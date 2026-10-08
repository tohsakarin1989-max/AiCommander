import pytest

from app.models.map_foundation import OperationalArea, UserAreaScope
from app.models.user import User
from app.services.map_foundation_service import MapFoundationService
from tests.test_auth_security import _build_client, _bootstrap_admin


def test_new_account_explicit_scope_is_atomic_and_does_not_inherit_default():
    client, sessions = _build_client()
    _bootstrap_admin(client)
    with sessions() as db:
        area = OperationalArea(code="second", name="第二厂区", status="active")
        db.add(area)
        db.commit()
        area_id = area.id
    response = client.post("/api/auth/users", json={
        "username": "scoped-user", "password": "StrongPassword!2026", "role": "analyst",
        "area_scopes": [{"operational_area_id": area_id, "access_level": "read"}],
    })
    assert response.status_code == 201, response.text
    user_id = response.json()["id"]
    with sessions() as db:
        scopes = db.query(UserAreaScope).filter_by(user_id=user_id).all()
        assert [(s.operational_area_id, s.access_level) for s in scopes] == [(area_id, "read")]
    assert client.get(f"/api/auth/users/{user_id}/area-scopes").json()[0]["area_name"] == "第二厂区"


def test_invalid_scope_does_not_create_account_and_empty_scope_is_explicit():
    client, sessions = _build_client()
    _bootstrap_admin(client)
    payload = {"username": "pending-user", "password": "StrongPassword!2026", "role": "analyst"}
    bad = client.post("/api/auth/users", json={**payload, "area_scopes": [{"operational_area_id": 999, "access_level": "write"}]})
    assert bad.status_code == 422
    with sessions() as db:
        assert db.query(User).filter_by(username="pending-user").count() == 0
    good = client.post("/api/auth/users", json={**payload, "area_scopes": []})
    assert good.status_code == 201
    with sessions() as db:
        assert db.query(UserAreaScope).filter_by(user_id=good.json()["id"]).count() == 0


def test_changing_default_area_does_not_rescope_existing_accounts():
    client, sessions = _build_client()
    _bootstrap_admin(client)
    created = client.post("/api/auth/users", json={"username": "legacy-user", "password": "StrongPassword!2026", "role": "viewer"})
    assert created.status_code == 201
    with sessions() as db:
        old = db.query(UserAreaScope).filter_by(user_id=created.json()["id"]).one().operational_area_id
        area = MapFoundationService.create_area(db, {"code": "new-default", "name": "新默认厂区", "is_default": True})
        assert area.id != old
        assert db.query(UserAreaScope).filter_by(user_id=created.json()["id"]).one().operational_area_id == old


def test_facility_lookup_filters_before_paging_and_preserves_scope(db_session):
    from app.models.jurisdiction import JurisdictionAsset
    from app.services.jurisdiction_service import JurisdictionService
    db_session.add_all([OperationalArea(id=i, code=f"area-{i}", name=f"厂区{i}") for i in (1, 2)])
    db_session.flush()
    db_session.add_all([JurisdictionAsset(name="老井%", external_id="PROD-001", asset_type="well", operational_area_id=1),
                        JurisdictionAsset(name="老井隐藏", asset_type="well", operational_area_id=2)])
    db_session.add_all([JurisdictionAsset(name=f"其他井{i}", asset_type="well", operational_area_id=1) for i in range(25)])
    db_session.commit()
    db_session.info['authorized_area_ids'] = (1,)
    assert [item.name for item in JurisdictionService.list_assets(db_session, keyword="老井", limit=1)] == ["老井%"]
    assert [item.name for item in JurisdictionService.list_assets(db_session, keyword="PROD-001")] == ["老井%"]
    assert len(JurisdictionService.list_assets(db_session, keyword="%")) == 1
    assert JurisdictionService.list_assets(db_session, keyword="老井", operational_area_id=2) == []


def test_non_admin_cannot_read_or_change_other_account_scope():
    client, _ = _build_client()
    _bootstrap_admin(client)
    account = client.post("/api/auth/users", json={"username": "limited", "password": "StrongPassword!2026", "role": "analyst", "area_scopes": []}).json()
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"username": "limited", "password": "StrongPassword!2026"}).status_code == 200
    assert client.get(f"/api/auth/users/{account['id']}/area-scopes").status_code == 403
    assert client.put(f"/api/auth/users/{account['id']}/area-scopes", json={"scopes": []}).status_code == 403


@pytest.fixture
def scope_account():
    client, sessions = _build_client()
    _bootstrap_admin(client)
    with sessions() as db:
        active = OperationalArea(code="scope-active", name="可用厂区", status="active")
        inactive = OperationalArea(code="scope-inactive", name="停用厂区", status="inactive")
        db.add_all([active, inactive])
        db.commit()
        active_id, inactive_id = active.id, inactive.id
    grants = [{"operational_area_id": active_id, "access_level": "read"}]
    created = client.post("/api/auth/users", json={
        "username": "scope-target", "password": "StrongPassword!2026", "role": "analyst",
        "area_scopes": grants,
    })
    assert created.status_code == 201
    return client, sessions, created.json()["id"], active_id, inactive_id, grants


def _stored_scopes(sessions, user_id):
    with sessions() as db:
        return sorted((scope.operational_area_id, scope.access_level) for scope in
                      db.query(UserAreaScope).filter_by(user_id=user_id).all())


def test_stale_scope_snapshot_is_conflict_and_never_overwrites_new_grant(scope_account):
    client, sessions, user_id, area_id, _, original = scope_account
    endpoint = f"/api/auth/users/{user_id}/area-scopes"
    latest = [{"operational_area_id": area_id, "access_level": "write"}]
    assert client.put(endpoint, json={"scopes": latest, "expected_scopes": original}).status_code == 200
    stale = client.put(endpoint, json={"scopes": [], "expected_scopes": original})
    assert stale.status_code == 409
    assert _stored_scopes(sessions, user_id) == [(area_id, "write")]
    assert client.get(endpoint).json()[0]["access_level"] == "write"


def test_empty_expected_scope_is_checked_and_empty_grant_can_be_restored_explicitly(scope_account):
    client, sessions, user_id, area_id, _, original = scope_account
    endpoint = f"/api/auth/users/{user_id}/area-scopes"
    # [] is a real expected snapshot, not omission of the concurrency guard.
    assert client.put(endpoint, json={"scopes": [], "expected_scopes": []}).status_code == 409
    assert _stored_scopes(sessions, user_id) == [(area_id, "read")]
    assert client.put(endpoint, json={"scopes": [], "expected_scopes": original}).status_code == 200
    assert _stored_scopes(sessions, user_id) == []
    assert client.put(endpoint, json={"scopes": original, "expected_scopes": original}).status_code == 409
    assert _stored_scopes(sessions, user_id) == []
    assert client.put(endpoint, json={"scopes": original, "expected_scopes": []}).status_code == 200
    assert _stored_scopes(sessions, user_id) == [(area_id, "read")]


@pytest.mark.parametrize("invalid", ["duplicate", "inactive", "missing", "access_level"])
def test_invalid_replacement_preserves_entire_existing_scope(scope_account, invalid):
    client, sessions, user_id, area_id, inactive_id, original = scope_account
    grants = [{"operational_area_id": area_id, "access_level": "write"}]
    if invalid == "duplicate":
        grants.append({"operational_area_id": area_id, "access_level": "read"})
    elif invalid in {"inactive", "missing"}:
        grants.append({"operational_area_id": inactive_id if invalid == "inactive" else 99999,
                       "access_level": "read"})
    else:
        grants[0]["access_level"] = "owner"
    response = client.put(f"/api/auth/users/{user_id}/area-scopes", json={
        "scopes": grants, "expected_scopes": original,
    })
    assert response.status_code == 422
    assert _stored_scopes(sessions, user_id) == [(area_id, "read")]


@pytest.mark.parametrize("invalid", ["duplicate", "inactive"])
def test_invalid_creation_scope_never_creates_user_or_partial_grants(scope_account, invalid):
    client, sessions, _, area_id, inactive_id, _ = scope_account
    grants = [{"operational_area_id": area_id, "access_level": "write"},
              {"operational_area_id": area_id if invalid == "duplicate" else inactive_id,
               "access_level": "read"}]
    before = _stored_scopes(sessions, 1)
    response = client.post("/api/auth/users", json={
        "username": "not-created", "password": "StrongPassword!2026", "role": "analyst",
        "area_scopes": grants,
    })
    assert response.status_code == 422
    with sessions() as db:
        assert db.query(User).filter_by(username="not-created").count() == 0
    assert _stored_scopes(sessions, 1) == before


def test_scope_snapshot_comparison_is_order_independent(scope_account):
    client, sessions, user_id, area_id, _, original = scope_account
    with sessions() as db:
        other = db.query(OperationalArea).filter_by(is_default=True).one().id
    endpoint = f"/api/auth/users/{user_id}/area-scopes"
    expanded = [*original, {"operational_area_id": other, "access_level": "write"}]
    assert client.put(endpoint, json={"scopes": expanded, "expected_scopes": original}).status_code == 200
    assert client.put(endpoint, json={"scopes": original, "expected_scopes": list(reversed(expanded))}).status_code == 200
    assert _stored_scopes(sessions, user_id) == [(area_id, "read")]
