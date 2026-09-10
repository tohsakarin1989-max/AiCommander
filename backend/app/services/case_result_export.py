"""受控本地成果导出；不执行用户命令，不把渲染器日志返回客户端。"""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import subprocess
from threading import BoundedSemaphore

from sqlalchemy.orm import Session

from app.services.case_result_document import CaseResultDocument, load_case_result_document


RENDERER = Path(__file__).resolve().parents[2] / "document-renderer" / "render-docx.cjs"
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 20 * 1024 * 1024
RENDER_TIMEOUT_SECONDS = 20
# 每个Web进程最多两个导出，不等待队列占用请求线程。
_slots = BoundedSemaphore(2)


class CaseResultExportError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def render_docx(document: CaseResultDocument) -> bytes:
    payload = json.dumps(asdict(document), ensure_ascii=False, allow_nan=False).encode()
    if len(payload) > MAX_INPUT_BYTES:
        raise CaseResultExportError("document_too_large")
    node = shutil.which("node")
    if not node or not (RENDERER.parent / "node_modules" / "docx").is_dir():
        raise CaseResultExportError("renderer_not_installed")
    if not _slots.acquire(blocking=False):
        raise CaseResultExportError("renderer_busy")
    try:
        # 不继承数据库密钥、模型凭据、代理配置或NODE_OPTIONS等代码加载选项。
        environment = {key: os.environ[key] for key in ("PATH", "LANG", "SYSTEMROOT") if key in os.environ}
        try:
            result = subprocess.run(
                [node, str(RENDERER)], input=payload, capture_output=True,
                cwd=RENDERER.parent, env=environment, timeout=RENDER_TIMEOUT_SECONDS,
                check=False, shell=False,
            )
        except subprocess.TimeoutExpired:
            raise CaseResultExportError("renderer_timeout") from None
        except OSError:
            raise CaseResultExportError("renderer_unavailable") from None
        if result.returncode:
            code = result.stderr.decode("utf-8", errors="replace").splitlines()
            if code and code[-1] == "frozen_map_renderer_required":
                raise CaseResultExportError("map_rendering_not_ready")
            raise CaseResultExportError("renderer_failed")
        if not result.stdout.startswith(b"PK\x03\x04") or len(result.stdout) > MAX_OUTPUT_BYTES:
            raise CaseResultExportError("invalid_renderer_output")
        return result.stdout
    finally:
        _slots.release()


def export_case_result_docx(db: Session, result_id: str) -> tuple[CaseResultDocument, bytes]:
    document = load_case_result_document(db, result_id)
    data = render_docx(document)
    # 返回前重新校验证据；渲染期间失效时不交付已生成文件。
    current = load_case_result_document(db, result_id)
    if current.content_sha256 != document.content_sha256:
        raise CaseResultExportError("result_changed")
    return document, data
