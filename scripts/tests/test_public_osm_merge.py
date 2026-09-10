import importlib.util
from pathlib import Path

import osmium
import pytest


SPEC = importlib.util.spec_from_file_location(
    "public_osm_merge", Path(__file__).parents[1] / "merge-public-osm-sources.py"
)
MERGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MERGE)
STAMP = "2026-09-08T20:21:01Z"


def source(tmp_path, name, content, timestamp=STAMP):
    xml = tmp_path / f"{name}.osm"
    xml.write_text(f'<osm version="0.6">{content}</osm>')
    pbf = tmp_path / f"{name}.osm.pbf"
    header = osmium.io.Header()
    if timestamp:
        header.set("osmosis_replication_timestamp", timestamp)
    with osmium.SimpleWriter(str(pbf), header=header) as writer:
        for obj in osmium.FileProcessor(str(xml)):
            writer.add(obj)
    return pbf


NODES = '<node id="1" version="1" lat="46" lon="124"/><node id="2" version="1" lat="46.1" lon="124.1"/>'
WAY = '<way id="1" version="1"><nd ref="2"/><nd ref="1"/><tag k="oneway" v="yes"/><tag k="highway" v="service"/></way>'
REL = '<relation id="1" version="1"><member type="way" ref="1" role="from"/><member type="node" ref="1" role="via"/><member type="way" ref="2" role="to"/><tag k="type" v="restriction"/><tag k="restriction" v="no_left_turn"/></relation>'


def test_merge_preserves_original_topology_and_deduplicates(tmp_path):
    a = source(tmp_path, "a", NODES + WAY + REL)
    b = source(tmp_path, "b", NODES + WAY)
    result = MERGE.merge([a, b], tmp_path / "out")
    assert result["objects"] == {"n": 2, "w": 1, "r": 1}
    assert result["duplicate_copies_removed"] == 3
    assert result["reference_completeness_verified"] is False
    objects = list(MERGE.signatures(tmp_path / "out/merged.osm.pbf"))
    assert objects == list(MERGE.signatures(a))
    assert (tmp_path / "out/merge-manifest.json").exists()


@pytest.mark.parametrize("replacement", [NODES.replace('lon="124"', 'lon="125"') + WAY,
                                          NODES + WAY.replace('ref="2"/><nd ref="1"', 'ref="1"/><nd ref="2"'),
                                          NODES + WAY.replace('v="yes"', 'v="no"'),
                                          NODES + WAY.replace('version="1"', 'version="2"')])
def test_conflicting_duplicates_fail_without_finished_output(tmp_path, replacement):
    a = source(tmp_path, "a", NODES + WAY)
    b = source(tmp_path, "b", replacement)
    with pytest.raises(ValueError, match="Conflicting"):
        MERGE.merge([a, b], tmp_path / "out")
    assert not (tmp_path / "out/merge-manifest.json").exists()
    assert not (tmp_path / "out/merged.osm.pbf").exists()


@pytest.mark.parametrize("timestamp", [None, "2026-09-07T20:21:01Z"])
def test_timestamp_mismatch_rejected_before_output(tmp_path, timestamp):
    a = source(tmp_path, "a", NODES)
    b = source(tmp_path, "b", NODES, timestamp)
    with pytest.raises(ValueError, match="timestamp"):
        MERGE.merge([a, b], tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("content", [NODES + NODES, '<node id="2" version="1" lat="46.1" lon="124.1"/><node id="1" version="1" lat="46" lon="124"/>'])
def test_unsorted_or_repeated_objects_rejected(tmp_path, content):
    a = source(tmp_path, "a", content)
    b = source(tmp_path, "b", NODES)
    with pytest.raises(ValueError, match="order"):
        MERGE.merge([a, b], tmp_path / "out")


def test_existing_output_and_repeated_source_rejected(tmp_path):
    a = source(tmp_path, "a", NODES)
    with pytest.raises(ValueError):
        MERGE.merge([a, a], tmp_path / "out")
    b = source(tmp_path, "b", NODES)
    output = tmp_path / "out"
    output.mkdir()
    with pytest.raises(FileExistsError):
        MERGE.merge([a, b], output)


def test_restriction_role_and_member_order_conflicts_are_not_dropped(tmp_path):
    a = source(tmp_path, "a", NODES + WAY + REL)
    b = source(tmp_path, "b", NODES + WAY + REL.replace('role="from"', 'role="to"'))
    with pytest.raises(ValueError, match="Conflicting public object: r1"):
        MERGE.merge([a, b], tmp_path / "out")
    assert not (tmp_path / "out/merged.osm.pbf").exists()


def test_source_change_during_processing_has_no_final_artifact(tmp_path, monkeypatch):
    a = source(tmp_path, "a", NODES)
    b = source(tmp_path, "b", NODES)
    original = MERGE.digest
    seen = {}

    def changed(path):
        seen[path] = seen.get(path, 0) + 1
        return "0" * 64 if path == a and seen[path] > 1 else original(path)

    monkeypatch.setattr(MERGE, "digest", changed)
    with pytest.raises(ValueError, match="changed"):
        MERGE.merge([a, b], tmp_path / "out")
    assert list((tmp_path / "out").iterdir()) == []


@pytest.mark.parametrize("content", ["", '<node id="1" version="1" visible="false"/>', '<node id="-1" version="1" lat="46" lon="124"/>'])
def test_empty_deleted_or_negative_source_fails(tmp_path, content):
    a = source(tmp_path, "a", content)
    b = source(tmp_path, "b", NODES)
    with pytest.raises(ValueError):
        MERGE.merge([a, b], tmp_path / "out")
    assert not (tmp_path / "out/merge-manifest.json").exists()


def test_cli_writes_manifest_and_stable_semantic_output(tmp_path, monkeypatch):
    import json

    a = source(tmp_path, "a", NODES + WAY)
    b = source(tmp_path, "b", NODES + WAY + REL)
    out = tmp_path / "out"
    monkeypatch.setattr("sys.argv", ["merge", "--source", str(a), "--source", str(b), "--output", str(out)])
    MERGE.main()
    result = json.loads((out / "merge-manifest.json").read_text())
    assert result["publish_ready"] is False
    assert result["artifact"]["sha256"] == MERGE.digest(out / "merged.osm.pbf")
    MERGE.merge([b, a], tmp_path / "reordered")
    assert list(MERGE.signatures(out / "merged.osm.pbf")) == list(MERGE.signatures(tmp_path / "reordered/merged.osm.pbf"))
