"""真实docx-js渲染；测试环境须提供Node及已安装的document-renderer依赖。"""
import io
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
from dataclasses import asdict
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest


RENDERER = Path(__file__).resolve().parents[1] / "document-renderer" / "render-docx.cjs"


def render(blocks, **envelope):
    node = os.environ.get("AIC_TEST_DOCX_NODE") or shutil.which("node")
    if not node:
        pytest.skip("Node未安装，不能验证真实Word渲染")
    if not (RENDERER.parent / "node_modules" / "docx").is_dir() and not os.environ.get("NODE_PATH"):
        pytest.skip("document-renderer依赖未安装；该跳过不代表Word导出验收通过")
    return subprocess.run([node, str(RENDERER)], input=json.dumps({
        "schema": "case-result-document-4.1.0-1", "blocks": blocks, **envelope,
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
        assert len(xml.findall(".//w:cantSplit", namespace)) == len(xml.findall(".//w:tr", namespace))
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


def test_real_docx_from_semantic_document_keeps_all_records_and_references(tmp_path):
    from app.services.case_result_document import build_case_result_document
    from app.services.case_result_snapshot import assemble_case_result
    from app.services.case_semantic_service import build_semantic_profile
    from test_case_result_snapshot import inputs

    profile, _, _ = inputs()
    description = "2026年9月10日22时至2026年9月11日2时30分。发现罐车。后来未见罐车。昨晚情况待核实。"
    records = [{"说明": f"合成记录{index}：" + "仅用于分页验证，未经核验，不作为正式事实。" * 3} for index in range(8)]
    profile.payload["semantics"] = build_semantic_profile({"description": description}, structured={"vehicle_info": records})
    source = {"id": "synthetic-long-result", "created_at": "2026-09-11T00:00:00Z", **assemble_case_result(profile, None, [])}
    document = build_case_result_document(source)
    result = render(asdict(document)["blocks"], schema=document.schema)
    assert result.returncode == 0, result.stderr.decode()
    with ZipFile(io.BytesIO(result.stdout)) as archive:
        xml = ElementTree.fromstring(archive.read("word/document.xml"))
        text = "\n".join(xml.itertext())
        for index in range(8):
            assert f"合成记录{index}：" in text
        assert "2026-09-10 22时（精度：小时）" in text
        assert "原文否定：罐车" in text and "表述冲突待核：罐车" in text
        assert "第8项 / 说明" in text
        assert source["content_sha256"] in text
    target = tmp_path / "synthetic-long-result.docx"
    target.write_bytes(result.stdout)
    print(f"synthetic_docx_visual_sample={target}")


def test_unknown_document_schema_stays_rejected():
    result = render([], schema="case-result-document-future")
    assert result.returncode != 0
    assert result.stderr.decode().splitlines()[-1] == "unsupported_document_schema"


@pytest.mark.parametrize("change", ["result_id", "content_sha256", "map_snapshot_id", "png_base64"])
def test_docx_rejects_image_from_different_frozen_result(change):
    from PIL import Image

    data = io.BytesIO()
    Image.new("RGB", (960, 700), "white").save(data, format="PNG")
    image = {"result_id": "result-1", "content_sha256": "digest", "map_snapshot_id": "map-1",
             "png_base64": base64.b64encode(data.getvalue()).decode()}
    image[change] = "wrong"
    result = render([{"kind": "map", "text": '{"map_snapshot_id":"map-1","candidates":[]}'}],
                    result_id="result-1", content_sha256="digest", map_image=image)
    assert result.returncode != 0 and result.stdout == b""
    assert result.stderr.decode().splitlines()[-1] == "invalid_frozen_map_image"
