"""Strict writes return only the saved case; complete read snapshots stay separate."""
from collections import Counter
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import database
from app.api import auth, cases
from app.models.case import Case
from app.models.case_pipeline import OutboxEvent
from app.models.case_source import CaseRevision
from app.models.map_foundation import OperationalArea, UserAreaScope
from app.models.user import AuditLog, User
from app.security import AuthMiddleware
from app.services.auth_service import AuthService


def test_strict_edit_releases_materialized_snapshot_before_independent_audit(tmp_path, monkeypatch, caplog):
    # Separate file-backed connections reproduce the real audit middleware lock.
    # A short SQLite timeout makes the old defect fail quickly, not a speed gate.
    engine = create_engine(f"sqlite:///{tmp_path / 'synthetic-edit-audit.sqlite'}",
                           connect_args={"check_same_thread": False, "timeout": 0.2})
    database.Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    with sessions() as db:
        db.add(OperationalArea(id=1, code="edit-audit", name="合成厂区", is_default=True))
        db.add(User(id=1, username="edit-audit", display_name="合成分析员", role="analyst",
                    password_hash=AuthService.hash_password("Synthetic-edit-audit-123!")))
        db.flush()
        db.add(UserAreaScope(user_id=1, operational_area_id=1, access_level="write"))
        db.commit()
    app = FastAPI()
    app.state.environment = "test"
    app.include_router(auth.router, prefix="/api/auth")
    app.include_router(cases.router, prefix="/api/cases")
    app.add_middleware(AuthMiddleware, session_factory=sessions, auth_required=True,
                       secure_cookie=False, allowed_origins=("http://testserver",))
    try:
        with TestClient(app) as client:
            assert client.get('/api/cases/1/edit-snapshot').status_code == 401
            assert client.post('/api/auth/login', json={"username": "edit-audit",
                "password": "Synthetic-edit-audit-123!"}).status_code == 200
            headers = {"Origin": "http://testserver"}
            created = client.post('/api/cases/', json={"description": "原始合成事实", "operational_area_id": 1,
                "initial_persons": [{"name": "合成原始人员"}]}, headers={**headers, "Idempotency-Key": "synthetic-edit-audit"})
            assert created.status_code == 200, created.text
            path = f'/api/cases/{created.json()["id"]}/edit-snapshot'
            initial = client.get(path).json()
            statements = Counter()

            def count_sql(_conn, _cursor, statement, _parameters, _context, _many):
                statements[statement.split(None, 1)[0].upper()] += 1

            event.listen(engine, "before_cursor_execute", count_sql)
            try:
                saved = client.put(path, json={"expected_revision": initial["source_revision"],
                    "case_payload": {"description": "明确更正后的合成事实"}}, headers=headers)
            finally:
                event.remove(engine, "before_cursor_execute", count_sql)
            assert saved.status_code == 200, saved.text
            assert set(saved.json()) == {"case"}
            assert saved.json()["case"]["description"] == "明确更正后的合成事实"
            print("authenticated_strict_put_sql_counts:", dict(statements))
            snapshot = client.get(path).json()
            assert snapshot["case"]["description"] == "明确更正后的合成事实"
            assert snapshot["initial_persons"][0]["name"] == "合成原始人员"
            with sessions() as db:
                current_revision = db.query(CaseRevision).filter_by(case_id=created.json()["id"]).order_by(
                    CaseRevision.revision.desc()).first().revision
                assert snapshot["source_revision"] == current_revision
                assert current_revision > initial["source_revision"]
                assert db.query(AuditLog).filter_by(action="api.mutation", method="PUT", path=path,
                                                    status_code=200).count() == 1
            conflict = client.put(path, json={"expected_revision": initial["source_revision"],
                "case_payload": {"description": "不得覆盖的旧页面内容"}}, headers=headers)
            assert conflict.status_code == 409
            with sessions() as db:
                assert db.query(AuditLog).filter_by(action="api.mutation", method="PUT", path=path,
                                                    status_code=409).count() == 1
                assert db.query(Case).one().description == "明确更正后的合成事实"
                assert db.query(CaseRevision).count() == 2
                assert db.query(OutboxEvent).filter_by(event_type="case.analysis.requested").count() == 2
            assert "database is locked" not in caplog.text
            assert "写入审计日志失败" not in caplog.text
    finally:
        engine.dispose()
