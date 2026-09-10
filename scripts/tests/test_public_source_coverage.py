import importlib.util
import json
from pathlib import Path

import pytest
from shapely.geometry import box


spec = importlib.util.spec_from_file_location(
    "source_coverage", Path(__file__).parents[1] / "verify-public-source-coverage.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_missing_strip_is_not_covered():
    result = module.coverage(box(0, 0, 2, 2), [box(0, 0, 1, 2)])
    assert result["coverage_verified"] is False
    assert result["uncovered_bounds"] == [1.0, 0.0, 2.0, 2.0]


def test_union_covers_target():
    assert module.coverage(box(0, 0, 2, 2), [box(0, 0, 1, 2), box(1, 0, 2, 2)])["coverage_verified"]


def test_poly_hole_remains_uncovered():
    poly = module.parse_poly("name\n1\n0 0\n3 0\n3 3\n0 3\n0 0\nEND\n!1\n1 1\n2 1\n2 2\n1 2\n1 1\nEND\nEND\n")
    assert not module.coverage(box(0, 0, 3, 3), [poly])["coverage_verified"]


@pytest.mark.parametrize("text", ["name\nEND", "name\n1\n0 0\nEND\nEND", "name\n1\n0 0\n1 0\n1 1\n0 0\nEND", "name\n!1\n0 0\n1 0\n1 1\n0 0\nEND\nEND", "name\n1\n0 0\n181 0\n1 1\n0 0\nEND\nEND"])
def test_invalid_poly_rejected(text):
    with pytest.raises(ValueError):
        module.parse_poly(text)


@pytest.mark.parametrize("covered", [True, False])
def test_cli_report_is_exclusive_and_not_publication(tmp_path, monkeypatch, covered):
    from shapely.geometry import mapping

    region = tmp_path / "region.json"
    region.write_text(json.dumps({"features": [{"geometry": mapping(box(0, 0, 2, 2))}]}))
    source = tmp_path / "source.poly"
    edge = 2 if covered else 1
    source.write_text(f"source\n1\n0 0\n{edge} 0\n{edge} 2\n0 2\n0 0\nEND\nEND\n")
    output = tmp_path / "report.json"
    monkeypatch.setattr("sys.argv", ["check", "--region", str(region), "--source-poly", str(source), "--output", str(output)])
    assert module.main() == (0 if covered else 1)
    result = json.loads(output.read_text())
    assert result["coverage_verified"] is covered
    assert result["publish_ready"] is False
    assert len(result["region_sha256"]) == 64
    with pytest.raises(FileExistsError):
        module.main()


def test_multiple_shells_and_invalid_shapes():
    poly = module.parse_poly("name\n1\n0 0\n1 0\n1 1\n0 0\nEND\n2\n2 2\n3 2\n3 3\n2 2\nEND\nEND")
    assert poly.geom_type == "MultiPolygon"
    with pytest.raises(ValueError):
        module.coverage(box(0, 0, 1, 1), [])
    with pytest.raises(ValueError):
        module.coverage(box(0, 0, 1, 1).centroid, [poly])


def test_hole_subtracts_all_preceding_overlapping_shells():
    poly = module.parse_poly("name\nA\n0 0\n3 0\n3 3\n0 3\n0 0\nEND\nB\n1 0\n4 0\n4 3\n1 3\n1 0\nEND\n!hole\n1.5 1\n2.5 1\n2.5 2\n1.5 2\n1.5 1\nEND\nEND")
    assert not module.coverage(box(1.5, 1, 2.5, 2), [poly])["coverage_verified"]
