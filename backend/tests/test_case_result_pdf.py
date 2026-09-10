import os
from pathlib import Path
import subprocess
from threading import BoundedSemaphore
from types import SimpleNamespace

import pytest

from app.models.case import Case
from app.services import case_result_pdf as pdf
from app.services.case_result_service import CaseResultService
from test_case_results import client_for, db_session, prepare, result_data  # noqa: F401


@pytest.fixture
def converter(monkeypatch):
    monkeypatch.setattr(pdf.shutil, "which", lambda name: "/trusted/soffice")
    monkeypatch.setattr(pdf, "_slots", BoundedSemaphore(1))
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-inherit")
    monkeypatch.setenv("HTTP_PROXY", "do-not-inherit")


def test_converter_isolated_profile_fixed_files_no_secrets_and_cleanup(converter, monkeypatch):
    directories = []

    def run(command, **kwargs):
        root = Path(kwargs["cwd"])
        directories.append(root)
        assert root.stat().st_mode & 0o077 == 0
        assert command[0] == "/trusted/soffice"
        assert command[1] == "-env:UserInstallation=" + (root / "profile").as_uri()
        assert kwargs["timeout"] == 45 and kwargs["shell"] is False
        assert "OPENAI_API_KEY" not in kwargs["env"] and "HTTP_PROXY" not in kwargs["env"]
        assert (root / "result.docx").read_bytes() == b"PK\x03\x04test"
        (root / "output/result.pdf").write_bytes(b"%PDF-1.7\nsynthetic\n%%EOF\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(pdf.subprocess, "run", run)
    assert pdf._convert_generated_docx(b"PK\x03\x04test").startswith(b"%PDF")
    assert not directories[0].exists()
    assert pdf._slots.acquire(blocking=False)


@pytest.mark.parametrize("failure", ["timeout", "bad_output", "missing_output", "exit_failure"])
def test_converter_failure_never_returns_partial_pdf(converter, monkeypatch, failure):
    directories = []

    def run(command, **kwargs):
        root = Path(kwargs["cwd"])
        directories.append(root)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 45, stderr=b"private-path")
        if failure == "bad_output":
            (root / "output/result.pdf").write_bytes(b"%PDF-without-trailer")
        return SimpleNamespace(returncode=1 if failure == "exit_failure" else 0)

    monkeypatch.setattr(pdf.subprocess, "run", run)
    with pytest.raises(pdf.CaseResultExportError) as error:
        pdf._convert_generated_docx(b"PK\x03\x04test")
    assert "private" not in str(error.value)
    assert not directories[0].exists()
    assert pdf._slots.acquire(blocking=False)


def test_pdf_download_auth_and_revocation_after_conversion(db_session, result_data, monkeypatch):
    prepare(db_session)
    result_id, _ = CaseResultService.freeze_completed_inputs(db_session, result_data[0])
    db_session.commit()
    url = f"/api/case-results/{result_id}/document.pdf"
    with client_for(db_session, None) as client:
        assert client.get(url).status_code == 401

    def convert_and_revoke(data):
        db_session.execute(Case.__table__.update().where(Case.id == 1).values(operational_area_id=2))
        db_session.commit()
        return b"%PDF-must-not-deliver"

    monkeypatch.setattr(pdf, "_convert_generated_docx", convert_and_revoke)
    with client_for(db_session, "viewer") as client:
        response = client.get(url)
        assert response.status_code == 404
        assert b"must-not-deliver" not in response.content


@pytest.mark.skipif(os.environ.get("AIC_TEST_PDF_OFFICE") != "1", reason="requires real installed offline office engine")
def test_real_pdf_download_contains_frozen_result(db_session, result_data, tmp_path):
    prepare(db_session)
    result_id, _ = CaseResultService.freeze_completed_inputs(db_session, result_data[0])
    db_session.commit()
    with client_for(db_session, "viewer") as client:
        response = client.get(f"/api/case-results/{result_id}/document.pdf")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content.startswith(b"%PDF-") and b"%%EOF" in response.content[-1024:]
    (tmp_path / "frozen-result.pdf").write_bytes(response.content)
