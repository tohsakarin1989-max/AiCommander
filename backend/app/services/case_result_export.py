"""受控本地成果导出；不执行用户命令，不把渲染器日志返回客户端。"""
from __future__ import annotations

from dataclasses import asdict
import base64
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
from threading import BoundedSemaphore

from sqlalchemy.orm import Session
from PIL import Image

from app.services.case_result_document import CaseResultDocument, load_case_result_document
from app.services.document_budget import document_budget, remaining_seconds


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


def render_docx(document: CaseResultDocument, *, map_image: bytes | None = None) -> bytes:
    data = asdict(document)
    if map_image is not None:
        if len(map_image) > 8 * 1024 * 1024:
            raise CaseResultExportError("invalid_map_image")
        maps = [json.loads(block.text) for block in document.blocks if block.kind == "map"]
        if len(maps) != 1 or not maps[0].get("map_snapshot_id"):
            raise CaseResultExportError("invalid_map_image")
        try:
            with Image.open(io.BytesIO(map_image)) as image:
                if image.format != "PNG" or image.width != 960 or not 500 <= image.height <= 1500:
                    raise ValueError("invalid_image")
                image.verify()
        except (OSError, ValueError, Image.DecompressionBombError):
            raise CaseResultExportError("invalid_map_image") from None
        data["map_image"] = {"result_id": document.result_id, "content_sha256": document.content_sha256,
                             "map_snapshot_id": maps[0]["map_snapshot_id"],
                             "png_base64": base64.b64encode(map_image).decode("ascii")}
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
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
                cwd=RENDERER.parent, env=environment, timeout=remaining_seconds(RENDER_TIMEOUT_SECONDS),
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


@document_budget
def export_case_result_docx(db: Session, result_id: str, road_artifact_id: str | None = None) -> tuple[CaseResultDocument, bytes]:
    document = load_case_result_document(db, result_id, road_artifact_id)
    maps = [json.loads(block.text) for block in document.blocks if block.kind == "map"]
    if any(item.get("map_snapshot_id") for item in maps):
        from app.services.case_map_image import CaseMapImageError, render_case_map_image

        try:
            image = (render_case_map_image(db, result_id, road_artifact_id=road_artifact_id)
                     if road_artifact_id else render_case_map_image(db, result_id))
        except CaseMapImageError:
            raise CaseResultExportError("map_rendering_not_ready") from None
        data = render_docx(document, map_image=image)
    else:
        data = render_docx(document)
    # 返回前重新校验证据；渲染期间失效时不交付已生成文件。
    current = load_case_result_document(db, result_id, road_artifact_id)
    if (current.content_sha256, current.road_artifact_sha256) != (document.content_sha256, document.road_artifact_sha256):
        raise CaseResultExportError("result_changed")
    return document, data
