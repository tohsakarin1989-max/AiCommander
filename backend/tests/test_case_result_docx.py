"""真实docx-js渲染；测试环境须提供Node及已安装的document-renderer依赖。"""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest


RENDERER = Path(__file__).resolve().parents[1] / "document-renderer" / "render-docx.cjs"


def render(blocks):
    node = os.environ.get("AIC_TEST_DOCX_NODE") or shutil.which("node")
    if not node:
        pytest.skip("Node未安装，不能验证真实Word渲染")
    if not (RENDERER.parent / "node_modules" / "docx").is_dir() and not os.environ.get("NODE_PATH"):
        pytest.skip("document-renderer依赖未安装；该跳过不代表Word导出验收通过")
    return subprocess.run([node, str(RENDERER)], input=json.dumps({
        "schema": "case-result-document-4.1.0-1", "blocks": blocks,
    }, ensure_ascii=False).encode(), capture_output=True, timeout=30, check=False)


def test_real_docx_chinese_tables_lines_and_markup_are_preserved(tmp_path):
    result = render([
        {"kind": "heading", "text": "案件统一研判成果"},
        {"kind": "paragraph", "text": "原文否定：未发现罐车\n候选待核验"},
        {"kind": "source", "text": '<script>不执行</script> & "原文"'},
        {"kind": "table", "text": "来源", "rows": [["引用", "case_profile:synthetic-1"], ["否定", "否"]]},
        {"kind": "map", "text": json.dumps({"map_snapshot_id": None, "candidates": []})},
    ])
    assert result.returncode == 0, result.stderr.decode()
    with ZipFile(io.BytesIO(result.stdout)) as archive:
        xml = ElementTree.fromstring(archive.read("word/document.xml"))
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        text = "\n".join(xml.itertext())
        assert "原文否定：未发现罐车" in text and "候选待核验" in text
        assert '<script>不执行</script> & "原文"' in text
        assert "case_profile:synthetic-1" in text
        assert xml.findall(".//w:tblHeader", namespace)
        assert not xml.findall(".//w:hyperlink", namespace)
        assert b'Noto Sans CJK SC' in archive.read("word/styles.xml")
    (tmp_path / "synthetic-result.docx").write_bytes(result.stdout)


@pytest.mark.parametrize("block,reason", [
    ({"kind": "map", "text": '{"map_snapshot_id":"map-1","candidates":[]}'}, "frozen_map_renderer_required"),
    ({"kind": "paragraph", "text": "原文\u0000不可静默删除"}, "invalid_document_character"),
    ({"kind": "shell", "text": "任何指令"}, "unsupported_document_block"),
])
def test_docx_rejects_missing_map_invalid_xml_and_unknown_blocks(block, reason):
    result = render([block])
    assert result.returncode != 0
    assert result.stdout == b""
    # Node may emit its own startup warning; the renderer's final error must be exact.
    assert result.stderr.decode().splitlines()[-1] == reason
