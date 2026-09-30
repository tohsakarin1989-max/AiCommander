"""New facility filters retain scope changes without caching row membership."""
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

import app.models  # noqa: F401
from app.models.case import Case
from app.models.case_facility_association import CaseFacilityAssociation
from app.models.case_source import CaseRevision, SourceReference
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import (
    FacilityIdentityDecision, FacilitySourceIdentity, MapSource, OperationalArea,
)
from app.models.user import User


@pytest.fixture
def scoped_facilities(db_session):
    """Two synthetic areas plus cross-area associations exercise both parents."""
    db = db_session
    db.add(User(id=1, username="synthetic-facility-scope", display_name="合成测试",
                password_hash="not-a-login", role="admin"))
    db.add_all([OperationalArea(id=i, code=f"scope-area-{i}", name=f"合成厂区{i}")
                for i in (1, 2)])
    db.flush()
    for i in (1, 2):
        db.add(MapSource(id=i, source_key=f"scope-source-{i}", name=f"合成台账{i}",
                         source_type="ledger", operational_area_id=i))
        db.add(JurisdictionAsset(id=i, name="同名合成井", asset_type="well",
                                 operational_area_id=i))
        db.add(Case(id=i, case_number=f"SYNTHETIC-SCOPE-{i}", operational_area_id=i))
    db.flush()
    for i in (1, 2):
        db.add(FacilitySourceIdentity(id=i, source_id=i, operational_area_id=i,
            native_asset_id=i, identity_key=f"scope-key-{i}", asset_type="well",
            identity_kind="exact_id"))
        db.add(CaseRevision(id=i, case_id=i, revision=1,
                            source_hash="synthetic-scope", payload={}))
    db.flush()
    for i in (1, 2):
        db.add(FacilityIdentityDecision(id=i, identity_id=i, operational_area_id=i,
            target_asset_id=i, sequence=1, action="bind", actor_id=1,
            note="合成权限验证", request_key=f"scope-decision-{i}"))
        db.add(SourceReference(id=i, case_id=i, source_revision_id=i,
                               kind="text", locator={}))
    db.flush()
    for identifier, (case_id, asset_id) in enumerate(((1, 1), (2, 2), (1, 2), (2, 1)), 1):
        db.add(CaseFacilityAssociation(id=identifier, case_id=case_id, asset_id=asset_id,
            source_reference_id=case_id, source_revision_id=case_id,
            relation_type="mentioned", note="合成权限验证",
            request_key=f"scope-link-{identifier}", created_by=1))
    db.commit()
    return db


def assert_visible(db, identity_ids, association_ids):
    for model, expected in (
        (FacilitySourceIdentity, identity_ids),
        (FacilityIdentityDecision, identity_ids),
        (CaseFacilityAssociation, association_ids),
    ):
        assert list(db.scalars(select(model.id).order_by(model.id))) == expected
        alias = aliased(model)
        assert list(db.scalars(select(alias.id).order_by(alias.id))) == expected


@pytest.mark.parametrize("steps", [
    pytest.param([((1, 2), [1, 2], [1, 2, 3, 4])], id="two-areas"),
    pytest.param([((1, 2), [1, 2], [1, 2, 3, 4]), ((1,), [1], [1])], id="same-list-shrink"),
    pytest.param([((1, 2), [1, 2], [1, 2, 3, 4]), ((), [], [])], id="same-list-empty"),
    pytest.param([((1,), [1], [1]), ((2,), [2], [2])], id="same-list-switch-area"),
    pytest.param([((1,), [1], [1]), ((1, 2), [1, 2], [1, 2, 3, 4])], id="same-list-expand"),
    pytest.param([((1,), [1], [1]), (None, [1, 2], [1, 2, 3, 4])], id="admin-after-restricted"),
    pytest.param([(None, [1, 2], [1, 2, 3, 4]), ((1,), [1], [1])], id="restricted-after-admin"),
])
def test_new_facility_filters_follow_live_scope(scoped_facilities, steps):
    db = scoped_facilities
    mutable_scope = []
    for areas, identities, associations in steps:
        if areas is None:
            db.info["authorized_area_ids"] = None
        else:
            # Reuse the same list: checking only list identity would retain access.
            mutable_scope[:] = areas
            db.info["authorized_area_ids"] = mutable_scope
        assert_visible(db, identities, associations)


def test_association_membership_reloads_asset_parent(scoped_facilities):
    db = scoped_facilities
    db.info["authorized_area_ids"] = (1,)
    assert_visible(db, [1], [1])
    # A fixed permission scope must not freeze the subquery's row membership.
    db.execute(JurisdictionAsset.__table__.update()
        .where(JurisdictionAsset.id == 1).values(operational_area_id=2))
    db.commit()
    assert_visible(db, [1], [])


def test_facility_scope_cache_does_not_cross_sessions(scoped_facilities):
    db = scoped_facilities
    db.info["authorized_area_ids"] = (1,)
    assert_visible(db, [1], [1])
    with Session(bind=db.bind) as other:
        other.info["authorized_area_ids"] = (2,)
        assert_visible(other, [2], [2])
    assert_visible(db, [1], [1])
