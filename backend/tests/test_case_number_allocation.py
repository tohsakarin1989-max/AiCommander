from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.database import AreaWriteAccessError
from app.models.case import Case
from app.services.case_service import CaseService
from test_case_search_page import search_db  # noqa: F401


def test_automatic_number_skips_hidden_area_without_exposing_hidden_case(search_db):
    search_db.add(Case(case_number='20261001-001', occurred_time=datetime(2026, 10, 1),
                       operational_area_id=2, description='不可见原文'))
    search_db.commit()
    search_db.info.update(authorized_area_ids=(1,), area_access_levels={1: 'write'}, default_operational_area_id=1)
    case = CaseService.create_case(search_db, None, datetime(2026, 10, 1), description='可见原文')
    assert case.case_number == '20261001-002'
    assert search_db.query(Case).count() == 1
    assert search_db.query(Case).filter_by(description='不可见原文').first() is None


def test_number_race_reallocates_only_automatic_number(search_db, monkeypatch):
    search_db.add(Case(case_number='20261001-001', occurred_time=datetime(2026, 10, 1), operational_area_id=1))
    search_db.commit()
    original = CaseService._generate_case_number
    calls = []
    def stale_once(db, occurred):
        calls.append(True)
        return '20261001-001' if len(calls) == 1 else original(db, occurred)
    monkeypatch.setattr(CaseService, '_generate_case_number', stale_once)
    created = CaseService.create_case(search_db, None, datetime(2026, 10, 1), operational_area_id=1)
    assert created.case_number == '20261001-002'
    assert len(calls) == 2
    with pytest.raises(IntegrityError):
        CaseService.create_case(search_db, '20261001-001', datetime(2026, 10, 1), operational_area_id=1)
    search_db.rollback()
    assert search_db.query(Case).count() == 2


def test_denied_write_never_allocates_number(search_db, monkeypatch):
    search_db.info.update(authorized_area_ids=(1,), area_access_levels={1: 'read'}, default_operational_area_id=1)
    def forbidden(*args):
        pytest.fail('Read-only request entered allocator')
    monkeypatch.setattr(CaseService, '_generate_case_number', forbidden)
    with pytest.raises(AreaWriteAccessError):
        CaseService.create_case(search_db, None, datetime(2026, 10, 1))


def test_non_number_integrity_failure_is_not_retried(search_db, monkeypatch):
    calls = []
    def allocate(*args):
        calls.append(True)
        return '20261001-001'
    monkeypatch.setattr(CaseService, '_generate_case_number', allocate)
    with pytest.raises(IntegrityError):
        CaseService.create_case(search_db, None, datetime(2026, 10, 1), operational_area_id=999)
    assert len(calls) == 1
    search_db.rollback()
    assert search_db.query(Case).count() == 0


def test_manual_create_savepoint_never_commits_before_outbox(search_db, monkeypatch):
    from app.services.case_pipeline_service import CasePipelineService
    monkeypatch.setattr(CasePipelineService, 'enqueue_case_change', lambda *args: (_ for _ in ()).throw(RuntimeError('pipeline failure')))
    with pytest.raises(RuntimeError):
        CaseService.create_case(search_db, None, datetime(2026, 10, 1), operational_area_id=1)
    search_db.rollback()
    assert search_db.query(Case).count() == 0


def test_number_collision_retries_are_bounded(search_db, monkeypatch):
    search_db.add(Case(case_number='20261001-001', occurred_time=datetime(2026, 10, 1), operational_area_id=1))
    search_db.commit()
    calls = []
    def always_stale(*args):
        calls.append(True)
        return '20261001-001'
    monkeypatch.setattr(CaseService, '_generate_case_number', always_stale)
    with pytest.raises(IntegrityError):
        CaseService.create_case(search_db, None, datetime(2026, 10, 1), operational_area_id=1)
    assert len(calls) == 8
    search_db.rollback()
    assert search_db.query(Case).count() == 1


@pytest.mark.parametrize('constraint,expected', [('uq_cases_case_number', True), ('ix_cases_case_number', True),
                                                ('cases_case_number_key', True), ('some_other_unique_key', False)])
def test_postgres_collision_classifier_is_constraint_specific(constraint, expected):
    from types import SimpleNamespace
    from app.services.case_number_service import is_number_collision
    original = Exception('unique violation')
    original.pgcode = '23505'
    original.diag = SimpleNamespace(constraint_name=constraint)
    assert is_number_collision(IntegrityError('insert', {}, original)) is expected


def test_allocation_order_uses_same_local_date_as_number_prefix():
    from datetime import date
    from app.services.case_import_values import allocation_order
    assert allocation_order({'occurred_time': '2026-12-02T00:30:00+08:00', 'description': 'fixture'}, 'UTC', 3) == (date(2026, 12, 2), 3)
    assert allocation_order({'occurred_time': 'invalid', 'description': 'fixture'}, 'UTC', 2) == (date.max, 2)
    # UTC chronology is reversed, but uniqueness prefixes use these source dates.
    earlier_prefix = allocation_order({'occurred_time': '2026-12-01T23:00:00-12:00', 'description': 'fixture'}, 'UTC', 4)
    later_prefix = allocation_order({'occurred_time': '2026-12-02T00:00:00+14:00', 'description': 'fixture'}, 'UTC', 2)
    assert earlier_prefix < later_prefix
