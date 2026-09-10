"""Public-source audit must not confuse reference closure with routability."""

import importlib.util
import json
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "public_osm_audit", Path(__file__).resolve().parents[2] / "scripts/audit-public-osm.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def run(objects):
    return MODULE.audit_records(lambda: iter(objects), ("大庆市", "齐齐哈尔市"))


def node(identifier):
    return {"type": "n", "id": identifier, "tags": {}, "refs": []}


def way(identifier, nodes, **tags):
    return {"type": "w", "id": identifier, "tags": tags,
            "refs": [("n", item, "") for item in nodes]}


def relation(identifier, refs, **tags):
    return {"type": "r", "id": identifier, "tags": tags, "refs": refs}


def test_unordered_nodes_and_ways_are_resolved_without_assuming_stream_order():
    result = run([way(10, [1, 2], highway="primary", oneway="yes"), node(2), node(1)])
    assert result["references"]["missing_way_nodes"] == 0
    assert result["roads"]["ways"] == 1
    assert result["roads"]["tag_counts"]["oneway"] == 1
    assert result["release_ready"] is False
    assert result["city_boundaries"][0]["status"] == "missing"


def test_missing_road_node_and_restriction_member_fail_reference_gate():
    result = run([node(1), way(10, [1, 99], highway="primary"),
                  relation(20, [("w", 10, "from"), ("n", 1, "via"),
                                ("w", 42, "to")], type="restriction",
                           restriction="no_left_turn")])
    assert result["references"]["missing_way_nodes"] == 1
    assert result["references"]["missing_restriction_members"] == 1
    assert result["reference_gate"] == "failed"


def test_boundary_with_present_way_but_missing_child_node_is_incomplete():
    result = run([way(10, [99]), relation(20, [("w", 10, "outer")],
                  type="boundary", boundary="administrative", admin_level="5",
                  name="大庆市")])
    assert result["city_boundaries"][0]["status"] == "incomplete_references"


def test_complete_boundary_refs_are_not_claimed_as_valid_polygon_or_full_coverage():
    result = run([node(1), node(2), way(10, [1, 2]),
                  relation(20, [("w", 10, "outer")], boundary="administrative",
                           admin_level="5", name="大庆市")])
    boundary = result["city_boundaries"][0]
    assert boundary["status"] == "references_present_geometry_unverified"
    assert result["release_ready"] is False
    assert result["routing_validated"] is False


def test_nested_boundary_is_explicitly_unverified_not_silently_complete():
    result = run([relation(21, [], type="multipolygon"),
                  relation(20, [("r", 21, "outer")], boundary="administrative",
                           admin_level="5", name="大庆市")])
    assert result["city_boundaries"][0]["status"] == "nested_members_unverified"


def test_duplicate_city_relations_are_ambiguous():
    result = run([relation(i, [], boundary="administrative", admin_level="5",
                           name="大庆市") for i in (20, 21)])
    assert result["city_boundaries"][0]["status"] == "ambiguous"


def test_missing_samples_are_bounded_but_counts_are_exact():
    result = run([way(10, list(range(1000)), highway="service")])
    assert result["references"]["missing_way_nodes"] == 1000
    assert len(result["references"]["samples"]) == 20


def test_bad_restriction_inventory_includes_all_incident_roads_without_guessing_role():
    objects = [node(1), node(2), node(3), node(4),
               way(10, [1, 2], highway='primary'), way(11, [1, 3], highway='service'),
               way(12, [3, 4], highway='primary'),
               relation(20, [('n', 1, 'via'), ('w', 10, 'to')],
                        type='restriction', restriction='no_left_turn')]
    result = run(objects)
    quarantine = result['restriction_quarantine']
    assert quarantine['exclude_way_ids'] == [10, 11]
    assert quarantine['exclude_node_ids'] == [1, 2]
    assert quarantine['relations'][0]['issues'] == ['missing_from']
    assert quarantine['routing_release_blocked'] is True
    assert quarantine['applied_to_graph'] is False
    assert len(objects[-1]['refs']) == 2  # source is not silently repaired


def test_unknown_restriction_location_blocks_instead_of_empty_safe_exclusion():
    result = run([relation(20, [('n', 99, 'via')], type='restriction', restriction='no_left_turn')])
    quarantine = result['restriction_quarantine']
    assert quarantine['unlocated_relation_ids'] == [20]
    assert quarantine['routing_release_blocked'] is True
    assert result['reference_gate'] == 'failed'


def test_valid_restriction_needs_no_quarantine_but_does_not_certify_routing():
    result = run([node(1), node(2), way(10, [1, 2]), way(11, [2, 1]),
                  relation(20, [('w', 10, 'from'), ('n', 1, 'via'), ('w', 11, 'to')],
                           type='restriction', restriction='no_left_turn')])
    assert result['restriction_quarantine']['relations'] == []
    assert result['restriction_quarantine']['routing_release_blocked'] is False
    assert result['routing_validated'] is False


def test_cli_report_hash_and_existing_output_protection(tmp_path, monkeypatch):
    source = tmp_path / "public.osm"
    source.write_bytes(b"fixture")
    output = tmp_path / "audit.json"
    monkeypatch.setattr("sys.argv", ["audit", str(source), "--output", str(output)])
    monkeypatch.setattr(MODULE, "read_records", lambda _: iter([node(1)]))
    assert MODULE.main() == 0
    report = json.loads(output.read_text())
    assert report["source"]["bytes"] == 7
    assert len(report["source"]["sha256"]) == 64
    assert report["release_ready"] is False
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        MODULE.main()
    assert output.read_bytes() == before


def test_cli_changed_input_does_not_write_report(tmp_path, monkeypatch):
    source = tmp_path / "public.osm"
    source.write_bytes(b"before")
    output = tmp_path / "audit.json"
    monkeypatch.setattr("sys.argv", ["audit", str(source), "--output", str(output)])

    def reader(_):
        source.write_bytes(b"after")
        return iter([])

    monkeypatch.setattr(MODULE, "read_records", reader)
    with pytest.raises(RuntimeError, match="Source changed"):
        MODULE.main()
    assert not output.exists()


@pytest.mark.parametrize("missing_role", ["from", "to", "via"])
def test_present_references_do_not_hide_missing_restriction_roles(missing_role):
    refs = [("w", 10, "from"), ("n", 1, "via"), ("w", 11, "to")]
    result = run([node(1), way(10, [1]), way(11, [1]), relation(
        20, [ref for ref in refs if ref[2] != missing_role],
        type="restriction", restriction="no_left_turn")])
    assert result["reference_gate"] == "passed"
    assert result["restriction_structure_gate"] == "failed"
    assert f"missing_{missing_role}" in result["restriction_structure"]["samples"][0]["issues"]


@pytest.mark.parametrize("value,role", [("no_entry", "from"), ("no_exit", "to")])
def test_valid_multiple_entry_exit_members_are_not_rejected(value, role):
    result = run([node(1), way(10, [1]), way(11, [1]), way(12, [1]), relation(
        20, [("w", 10, "from"), ("n", 1, "via"), ("w", 11, "to"),
             ("w", 12, role)], type="restriction", restriction=value)])
    assert result["restriction_structure_gate"] == "passed"
    assert result["routing_validated"] is False


@pytest.mark.parametrize("refs,issue", [
    ([("n", 1, "from"), ("n", 1, "via"), ("w", 11, "to")], "invalid_from_type"),
    ([("w", 10, "from"), ("n", 1, "via"), ("w", 12, "via"),
      ("w", 11, "to")], "invalid_via_shape"),
    ([("w", 10, "from"), ("w", 12, "from"), ("n", 1, "via"),
      ("w", 11, "to")], "invalid_from_count"),
])
def test_invalid_restriction_member_shapes_fail(refs, issue):
    result = run([node(1), way(10, [1]), way(11, [1]), way(12, [1]), relation(
        20, refs, type="restriction", restriction="no_left_turn")])
    assert issue in result["restriction_structure"]["samples"][0]["issues"]


@pytest.mark.parametrize("tags", [
    {"type": "restriction:hgv", "restriction": "no_left_turn"},
    {"type": "restriction", "restriction:motorcar": "no_left_turn"},
    {"type": "restriction", "restriction:conditional": "no_left_turn @ (Mo-Fr)"},
])
def test_qualified_restrictions_are_counted_but_semantics_remain_unverified(tags):
    result = run([node(1), way(10, [1]), way(11, [1]), relation(
        20, [("w", 10, "from"), ("n", 1, "via"), ("w", 11, "to")], **tags)])
    assert result["restrictions"] == 1
    assert result["restriction_structure_gate"] == "unverified"


def test_cli_fails_for_structure_even_when_all_references_exist(tmp_path, monkeypatch):
    source = tmp_path / "public.osm"
    source.write_bytes(b"fixture")
    output = tmp_path / "audit.json"
    monkeypatch.setattr("sys.argv", ["audit", str(source), "--output", str(output)])
    monkeypatch.setattr(MODULE, "read_records", lambda _: iter([
        node(1), way(10, [1]), relation(20, [("w", 10, "from"), ("n", 1, "via")],
                                     type="restriction", restriction="no_left_turn")]))
    assert MODULE.main() == 1
    assert json.loads(output.read_text())["reference_gate"] == "passed"
