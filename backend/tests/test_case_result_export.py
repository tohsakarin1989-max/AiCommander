import io
import subprocess
from threading import BoundedSemaphore
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from app.services import case_result_export as exports
from app.services.case_result_document import CaseResultDocument
from app.services.case_result_service import CaseResultService
from test_case_results import client_for, db_session, prepare, result_data  # noqa: F401


@pytest.fixture
def renderer_environment(monkeypatch, tmp_path):
    script = tmp_path / "render-docx.cjs"
    (tmp_path / "node_modules" / "docx").mkdir(parents=True)
    monkeypatch.setattr(exports, "RENDERER", script)
    monkeypatch.setattr(exports.shutil, "which", lambda name: "/trusted/node")
    monkeypatch.setattr(exports, "_slots", BoundedSemaphore(1))
    return CaseResultDocument("case-result-document-4.1.0-1", "result", "digest", ())


def test_renderer_uses_fixed_command_strips_secrets_and_releases_slot(monkeypatch, renderer_environment):
    monkeypatch.setenv("OPENAI_API_KEY", "not-for-renderer")
    monkeypatch.setenv("NODE_OPTIONS", "not-for-renderer")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=b"PK\x03\x04synthetic", stderr=b"")

    monkeypatch.setattr(exports.subprocess, "run", run)
    assert exports.render_docx(renderer_environment).startswith(b"PK")
    command, options = calls[0]
    assert command == ["/trusted/node", str(exports.RENDERER)]
    assert options["shell"] is False and options["timeout"] == 20
    assert "OPENAI_API_KEY" not in options["env"] and "NODE_OPTIONS" not in options["env"]
    assert exports._slots.acquire(blocking=False)


@pytest.mark.parametrize("failure,expected", [
    (subprocess.TimeoutExpired("renderer", 20, stderr=b"private internal path"), "renderer_timeout"),
    (OSError("private internal path"), "renderer_unavailable"),
])
def test_renderer_timeout_or_os_error_is_sanitized_and_slot_released(monkeypatch, renderer_environment, failure, expected):
    def run(*args, **kwargs):
        raise failure

    monkeypatch.setattr(exports.subprocess, "run", run)
    with pytest.raises(exports.CaseResultExportError, match=expected) as captured:
        exports.render_docx(renderer_environment)
    assert "private" not in str(captured.value)
    assert exports._slots.acquire(blocking=False)


def test_busy_renderer_does_not_start_a_process(monkeypatch, renderer_environment):
    exports._slots.acquire()
    monkeypatch.setattr(exports.subprocess, "run", lambda *args, **kwargs: pytest.fail("不应启动"))
    with pytest.raises(exports.CaseResultExportError, match="renderer_busy"):
        exports.render_docx(renderer_environment)


def test_download_auth_and_no_renderer_on_revoked_result(db_session, result_data, monkeypatch):
    prepare(db_session)
    result_data[2].evidence_refs = ["case:2"]
    db_session.info["authorized_area_ids"] = (1, 2)
    db_session.commit()
    saved, _ = CaseResultService.create_current(db_session, 1)
    db_session.commit()
    monkeypatch.setattr(exports, "render_docx", lambda document: pytest.fail("无权限不得渲染"))
    url = f"/api/case-results/{saved['id']}/document.docx"
    with client_for(db_session, None) as client:
        assert client.get(url).status_code == 401
    db_session.info["authorized_area_ids"] = (1,)
    with client_for(db_session, "viewer") as client:
        response = client.get(url)
        assert response.status_code == 404
        assert "case:2" not in response.text


def test_real_download_returns_readable_docx_and_map_failure_is_explicit(db_session, result_data):
    if not (exports.RENDERER.parent / "node_modules" / "docx").is_dir():
        pytest.skip("未安装真实Word渲染依赖，不能计入下载验收")
    prepare(db_session)
    base_id, _ = CaseResultService.freeze_completed_inputs(db_session, result_data[0])
    advanced, _ = CaseResultService.create_current(db_session, 1)
    db_session.commit()
    with client_for(db_session, "viewer") as client:
        response = client.get(f"/api/case-results/{base_id}/document.docx")
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "attachment;" in response.headers["content-disposition"]
        with ZipFile(io.BytesIO(response.content)) as archive:
            assert "案件统一研判成果" in archive.read("word/document.xml").decode()
        unavailable = client.get(f"/api/case-results/{advanced['id']}/document.docx")
        assert unavailable.status_code == 503
        assert "地图文件渲染尚未就绪" in unavailable.text
        assert "node_modules" not in unavailable.text


def test_result_revoked_while_rendering_is_not_delivered(db_session, result_data, monkeypatch):
    from app.models.case import Case

    prepare(db_session)
    base_id, _ = CaseResultService.freeze_completed_inputs(db_session, result_data[0])
    db_session.commit()

    def render_and_revoke(document):
        db_session.execute(Case.__table__.update().where(Case.id == 1).values(operational_area_id=2))
        db_session.commit()
        return b"PK\x03\x04must-not-deliver"

    monkeypatch.setattr(exports, "render_docx", render_and_revoke)
    with client_for(db_session, "viewer") as client:
        response = client.get(f"/api/case-results/{base_id}/document.docx")
        assert response.status_code == 404
        assert b"must-not-deliver" not in response.content
