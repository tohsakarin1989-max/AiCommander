"""Independent SQLite sessions, synthetic data, no external connections."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models.case import Case
from app.models.case_draft import CaseDraft
from app.models.case_source import CaseRevision
from app.models.case_submission import CaseSubmissionReceipt
from app.models.map_foundation import OperationalArea
from app.models.user import User
from app.services.case_draft_service import save_draft, submit_draft
from app.services.case_edit_service import CaseEditConflict, source_revision, update_case_checked


def make_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'private-concurrent.sqlite'}", connect_args={"timeout": 20})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(OperationalArea(id=1, code="v71-concurrent", name="合成厂区"))
        db.add(User(id=71, username="v71-concurrent", display_name="合成用户", password_hash="not-a-login", role="admin"))
        db.commit()
    return engine


def identify(db):
    db.info.update(principal_user_id=71, authorized_area_ids=(1,),
                   area_access_levels={1: "write"}, default_operational_area_id=1)


def test_parallel_draft_save_and_formal_submit_are_once_only(tmp_path):
    engine, draft_id = make_engine(tmp_path), str(uuid4())
    barrier = Barrier(4)

    def save(_):
        with Session(engine) as db:
            identify(db)
            barrier.wait(timeout=10)
            row = save_draft(db, draft_id, expected_revision=0, operational_area_id=1,
                             form_snapshot={"text": "同时保存的不完整草稿"})
            return row.id, row.revision, row.submission_key

    def submit(_):
        with Session(engine) as db:
            identify(db)
            barrier.wait(timeout=10)
            payload = {"description": "合成并发提交", "operational_area_id": 1}
            row = submit_draft(db, draft_id, expected_revision=1, request_payload=payload, values=payload)
            return row.submitted_case_id, row.revision

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            assert len(set(pool.map(save, range(4)))) == 1
        with ThreadPoolExecutor(max_workers=4) as pool:
            assert len(set(pool.map(submit, range(4)))) == 1
        with Session(engine) as db:
            assert db.query(Case).count() == db.query(CaseRevision).count() == 1
            assert db.query(CaseDraft).count() == db.query(CaseSubmissionReceipt).count() == 1
            assert db.query(CaseDraft).one().status == "submitted"
    finally:
        engine.dispose()


def test_parallel_strict_edits_allow_one_writer_and_return_conflict(tmp_path):
    engine, draft_id = make_engine(tmp_path), str(uuid4())
    with Session(engine) as db:
        identify(db)
        save_draft(db, draft_id, expected_revision=0, operational_area_id=1, form_snapshot={})
        payload = {"description": "共同原始版本", "operational_area_id": 1}
        case_id = submit_draft(db, draft_id, expected_revision=1, request_payload=payload, values=payload).submitted_case_id
        revision = source_revision(db, case_id)
    barrier = Barrier(2)

    def edit(number):
        with Session(engine) as db:
            identify(db)
            barrier.wait(timeout=10)
            try:
                case = update_case_checked(db, case_id, {"description": f"编辑者{number}输入"}, expected_revision=revision)
                return "saved", case.description
            except CaseEditConflict as exc:
                return "conflict", exc.current_revision

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(edit, range(2)))
        assert sorted(outcome[0] for outcome in outcomes) == ["conflict", "saved"]
        with Session(engine) as db:
            assert db.get(Case, case_id).description == next(value for kind, value in outcomes if kind == "saved")
            assert source_revision(db, case_id) == revision + 1
    finally:
        engine.dispose()
