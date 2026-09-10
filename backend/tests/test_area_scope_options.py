"""Request-local filter reuse must never retain a previous authorization scope."""
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import aliased, sessionmaker

import app.database as database
from app.models.case import Case, CaseVehicle
from app.models.map_foundation import OperationalArea


def seed(db):
    db.add_all([OperationalArea(id=i, code=f'scope-{i}', name=f'辖区{i}') for i in (1, 2)])
    db.flush()
    for i in (1, 2):
        db.add(Case(id=i, case_number=f'SCOPE-{i}', occurred_time=datetime(2026, 9, 1),
                    operational_area_id=i, description='合成'))
    db.commit()


def ids(db):
    return list(db.scalars(select(Case.id).order_by(Case.id)))


def test_same_scope_does_not_rebuild_every_query(db_session):
    seed(db_session)
    db_session.info['authorized_area_ids'] = (1,)
    with patch.object(database, 'with_loader_criteria', wraps=database.with_loader_criteria) as build:
        assert ids(db_session) == [1]
        initial = build.call_count
        assert initial > 0
        for _ in range(5):
            assert ids(db_session) == [1]
        assert build.call_count == initial


def test_scope_changes_empty_admin_and_in_place_mutation(db_session):
    seed(db_session)
    scope = [1, 2]
    db_session.info['authorized_area_ids'] = scope
    assert ids(db_session) == [1, 2]
    scope.pop()
    assert ids(db_session) == [1]
    scope.clear()
    assert ids(db_session) == []
    db_session.info['authorized_area_ids'] = None
    assert ids(db_session) == [1, 2]
    db_session.info['authorized_area_ids'] = (2,)
    assert ids(db_session) == [2]
    alias = aliased(Case)
    assert list(db_session.scalars(select(alias.id))) == [2]


def test_cached_filters_still_query_current_case_membership(db_session):
    seed(db_session)
    db_session.add_all([CaseVehicle(case_id=i, plate_number=f'SYNTHETIC-{i}') for i in (1, 2)])
    db_session.commit()
    db_session.info['authorized_area_ids'] = (1,)
    assert list(db_session.scalars(select(CaseVehicle.case_id))) == [1]
    with sessionmaker(bind=db_session.bind)() as other:
        other.info['authorized_area_ids'] = (2,)
        assert ids(other) == [2]
    # Moving a row in the database must not freeze membership in the filter cache.
    db_session.execute(Case.__table__.update().where(Case.id == 1).values(operational_area_id=2))
    db_session.commit()
    assert ids(db_session) == []
    assert list(db_session.scalars(select(CaseVehicle.case_id))) == []
