"""Convert only server-generated frozen DOCX; never accept uploaded files here."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from threading import BoundedSemaphore

from app.services.case_result_document import load_case_result_document
from app.services.case_result_export import CaseResultExportError, export_case_result_docx

MAX_BYTES = 20 * 1024 * 1024
TIMEOUT_SECONDS = 45
_slots = BoundedSemaphore(1)


def _convert_generated_docx(data: bytes) -> bytes:
    if len(data) > MAX_BYTES or not data.startswith(b"PK\x03\x04"):
        raise CaseResultExportError("invalid_pdf_source")
    office = shutil.which("soffice")
    if not office:
        raise CaseResultExportError("pdf_renderer_not_installed")
    if not _slots.acquire(blocking=False):
        raise CaseResultExportError("pdf_renderer_busy")
    try:
        with tempfile.TemporaryDirectory(prefix="aic-result-pdf-") as directory:
            root = Path(directory)
            source = root / "result.docx"
            output = root / "output"
            output.mkdir(mode=0o700)
            source.write_bytes(data)
            source.chmod(0o600)
            # Fontconfig is trusted operator configuration, never an API input.
            environment = {key: os.environ[key] for key in (
                "PATH", "LANG", "SYSTEMROOT", "TMPDIR", "FONTCONFIG_FILE", "FONTCONFIG_PATH",
            ) if key in os.environ}
            command = [office, "-env:UserInstallation=" + (root / "profile").as_uri(),
                       "--headless", "--nologo", "--nodefault", "--norestore",
                       "--convert-to", "pdf:writer_pdf_Export", "--outdir", str(output), str(source)]
            try:
                result = subprocess.run(command, cwd=root, env=environment, capture_output=True,
                                        timeout=TIMEOUT_SECONDS, shell=False, check=False)
            except subprocess.TimeoutExpired:
                raise CaseResultExportError("pdf_renderer_timeout") from None
            except OSError:
                raise CaseResultExportError("pdf_renderer_unavailable") from None
            target = output / "result.pdf"
            if result.returncode or target.is_symlink() or not target.is_file():
                raise CaseResultExportError("pdf_renderer_failed")
            if not 0 < target.stat().st_size <= MAX_BYTES:
                raise CaseResultExportError("pdf_output_too_large")
            with target.open("rb") as stream:
                pdf = stream.read(MAX_BYTES + 1)
            if len(pdf) > MAX_BYTES or not pdf.startswith(b"%PDF-") or b"%%EOF" not in pdf[-1024:]:
                raise CaseResultExportError("invalid_pdf_output")
            return pdf
    except OSError:
        raise CaseResultExportError("pdf_renderer_unavailable") from None
    finally:
        _slots.release()


def export_case_result_pdf(db, result_id: str):
    document, docx = export_case_result_docx(db, result_id)
    data = _convert_generated_docx(docx)
    current = load_case_result_document(db, result_id)
    if current.content_sha256 != document.content_sha256:
        raise CaseResultExportError("result_changed")
    return document, data
