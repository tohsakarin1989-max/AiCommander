import importlib.util
import json
from pathlib import Path

import osmium
import pytest
from shapely.geometry import box, mapping


SPEC = importlib.util.spec_from_file_location("road_extract", Path(__file__).parents[1] / "extract-public-roads.py")
EXTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXTRACT)


def inputs(tmp_path, *, missing=False, unrelated_missing=False):
    source = tmp_path / "source.osm"
    text = '''<osm version="0.6">
      <node id="1" lon="123" lat="46.5"/><node id="2" lon="126" lat="46.5"/>
      <node id="3" lon="127" lat="46.5"/><node id="4" lon="128" lat="46.5"/>
      <node id="5" lon="129" lat="46.5"/>
      <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="primary"/><tag k="oneway" v="yes"/></way>
      <way id="20"><nd ref="2"/><nd ref="3"/><tag k="highway" v="primary"/></way>
      <way id="30"><nd ref="3"/><nd ref="4"/><tag k="highway" v="service"/></way>
      <way id="40"><nd ref="4"/><nd ref="5"/><tag k="highway" v="service"/></way>
      <relation id="100"><member type="way" ref="10" role="from"/><member type="node" ref="2" role="via"/><member type="way" ref="20" role="to"/><tag k="type" v="restriction"/><tag k="restriction" v="no_left_turn"/></relation>
      <relation id="200"><member type="way" ref="20" role="from"/><member type="way" ref="30" role="via"/><member type="way" ref="40" role="to"/><tag k="type" v="restriction"/><tag k="restriction:conditional" v="no_right_turn @ (Mo-Fr)"/></relation>
    </osm>'''
    if missing:
        text = text.replace('ref="40" role="to"', 'ref="99" role="to"')
    if unrelated_missing:
        text = text.replace('</osm>', '<relation id="300"><member type="way" ref="999" role="to"/><tag k="type" v="restriction"/></relation></osm>')
    source.write_text(text)
    region = tmp_path / "region"
    region.mkdir()
    geometry = region / "extraction-region.geojson"
    geometry.write_text(json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": mapping(box(124, 46, 125, 47)), "properties": {}}]}))
    (region / "region-manifest.json").write_text(json.dumps({"source": {"sha256": EXTRACT.digest(source)}, "files": [{"filename": geometry.name, "sha256": EXTRACT.digest(geometry)}]}))
    return source, region


def test_crossing_road_and_transitive_restrictions_remain_complete(tmp_path):
    source, region = inputs(tmp_path)
    result = EXTRACT.extract(source, region, tmp_path / "out")
    assert result["seed_road_count"] == 1  # Neither endpoint is inside the target.
    assert result["objects"] == {"n": 5, "w": 4, "r": 2}
    assert result["reference_complete"] is True
    assert result["routing_validated"] is False
    rows = []
    for obj in osmium.FileProcessor(str(tmp_path / "out/roads.osm.pbf")):
        if obj.is_way():
            rows.append((obj.id, [n.ref for n in obj.nodes], dict(obj.tags)))
    assert rows[0] == (10, [1, 2], {"highway": "primary", "oneway": "yes"})


def test_missing_relevant_member_cannot_be_dropped(tmp_path):
    source, region = inputs(tmp_path, missing=True)
    with pytest.raises(ValueError, match="Missing"):
        EXTRACT.extract(source, region, tmp_path / "out")
    assert not (tmp_path / "out/road-manifest.json").exists()
    assert not (tmp_path / "out/roads.osm.pbf").exists()


def test_unrelated_restriction_is_explicitly_outside_extraction(tmp_path):
    source, region = inputs(tmp_path, unrelated_missing=True)
    result = EXTRACT.extract(source, region, tmp_path / "out")
    assert result["excluded_restriction_ids"] == [300]
    assert result["source_reference_completeness_verified"] is False


def test_wrong_source_or_region_digest_rejected(tmp_path):
    source, region = inputs(tmp_path)
    source.write_text(source.read_text().replace('v="yes"', 'v="no"'))
    with pytest.raises(ValueError, match="binding"):
        EXTRACT.extract(source, region, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_existing_output_is_not_replaced(tmp_path):
    source, region = inputs(tmp_path)
    output = tmp_path / "out"
    output.mkdir()
    with pytest.raises(FileExistsError):
        EXTRACT.extract(source, region, output)


def refresh(source, region):
    path = region / "region-manifest.json"
    manifest = json.loads(path.read_text())
    manifest["source"]["sha256"] = EXTRACT.digest(source)
    manifest["files"][0]["sha256"] = EXTRACT.digest(region / "extraction-region.geojson")
    path.write_text(json.dumps(manifest))


def test_missing_explicit_via_node_rejected_after_actual_readback(tmp_path):
    source, region = inputs(tmp_path)
    source.write_text(source.read_text().replace('ref="2" role="via"', 'ref="99" role="via"'))
    refresh(source, region)
    with pytest.raises(ValueError, match="Missing extracted"):
        EXTRACT.extract(source, region, tmp_path / "out")
    assert list((tmp_path / "out").iterdir()) == []


def test_bridge_crossing_has_distinct_nodes_and_keeps_layer(tmp_path):
    source, region = inputs(tmp_path)
    text = source.read_text().replace('<way id="10">', '''
      <node id="6" lon="124.5" lat="46"/><node id="7" lon="124.5" lat="47"/>
      <way id="10">''')
    text = text.replace('<relation id="100">', '''
      <way id="50"><nd ref="6"/><nd ref="7"/><tag k="highway" v="primary"/><tag k="bridge" v="yes"/><tag k="layer" v="1"/></way>
      <relation id="100">''')
    source.write_text(text)
    refresh(source, region)
    result = EXTRACT.extract(source, region, tmp_path / "out")
    assert result["seed_road_count"] == 2
    nodes, roads = set(), {}
    for obj in osmium.FileProcessor(str(tmp_path / "out/roads.osm.pbf")):
        if obj.is_node():
            nodes.add(obj.id)
        if obj.is_way():
            roads[obj.id] = ([n.ref for n in obj.nodes], dict(obj.tags))
    assert nodes == set(range(1, 8))
    assert set(roads[50][0]).isdisjoint(roads[10][0])
    assert roads[50][1]["bridge"] == "yes"
    assert roads[50][1]["layer"] == "1"


def test_missing_node_on_source_highway_fails_before_publication(tmp_path):
    source, region = inputs(tmp_path)
    source.write_text(source.read_text().replace('<nd ref="1"/>', '<nd ref="999"/>'))
    refresh(source, region)
    with pytest.raises(ValueError, match="Missing road geometry"):
        EXTRACT.extract(source, region, tmp_path / "out")


def test_nested_missing_relation_cannot_be_silently_removed(tmp_path):
    source, region = inputs(tmp_path)
    source.write_text(source.read_text().replace('<relation id="100">', '<relation id="100"><member type="relation" ref="999" role="via"/>'))
    refresh(source, region)
    with pytest.raises(ValueError, match="Missing relation"):
        EXTRACT.extract(source, region, tmp_path / "out")


def test_source_replacement_during_extract_has_no_finished_artifact(tmp_path, monkeypatch):
    source, region = inputs(tmp_path)
    original = EXTRACT.digest
    seen = 0

    def changed(path):
        nonlocal seen
        if path == source:
            seen += 1
            if seen > 1:
                return "0" * 64
        return original(path)

    monkeypatch.setattr(EXTRACT, "digest", changed)
    with pytest.raises(ValueError, match="changed"):
        EXTRACT.extract(source, region, tmp_path / "out")
    assert list((tmp_path / "out").iterdir()) == []


def test_cli_report_and_empty_scope(tmp_path, monkeypatch):
    source, region = inputs(tmp_path)
    output = tmp_path / "out"
    monkeypatch.setattr("sys.argv", ["extract", str(source), "--region-directory", str(region), "--output", str(output)])
    EXTRACT.main()
    result = json.loads((output / "road-manifest.json").read_text())
    assert result["artifact"]["sha256"] == EXTRACT.digest(output / "roads.osm.pbf")
    assert result["publish_ready"] is False
    geometry = region / "extraction-region.geojson"
    geometry.write_text(json.dumps({"features": [{"geometry": mapping(box(0, 0, 1, 1))}]}))
    refresh(source, region)
    with pytest.raises(ValueError, match="No public roads"):
        EXTRACT.extract(source, region, tmp_path / "empty")
