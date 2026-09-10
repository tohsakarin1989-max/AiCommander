import importlib.util
import json
import tempfile
import unittest
import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from test_public_map_region import REGION, fixture


SPEC = importlib.util.spec_from_file_location(
    "place_builder", Path(__file__).parents[1] / "build-public-place-index.py"
)
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class PlaceBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "public.osm"
        content = fixture().replace('<node id="1" lat="46" lon="124"/>',
            '<node id="1" lat="46" lon="124"><tag k="name" v="测试村"/>'
            '<tag k="name:en" v="Test Village"/><tag k="place" v="village"/></node>')
        content = content.replace('<relation id="20">',
            '<way id="11"><nd ref="1"/><nd ref="2"/>'
            '<tag k="name" v="测试路"/><tag k="highway" v="residential"/></way>'
            '<relation id="20">')
        self.source.write_text(content)
        self.region = self.root / "region"
        REGION.prepare(self.source, self.region, 30,
                       {20: {"name": "测试市", "admin_code": "000001"}})

    def tearDown(self):
        self.temp.cleanup()

    def reprepare(self):
        self.region = self.root / "updated-region"
        REGION.prepare(self.source, self.region, 30,
                       {20: {"name": "测试市", "admin_code": "000001"}})

    def test_real_nodes_roads_and_areas_are_searchable_with_source_ids(self):
        output = self.root / "places.sqlite"
        report = BUILDER.build(self.source, self.region, output)
        self.assertEqual(report["place_count"], 3)
        self.assertEqual(BUILDER.search_index(output, "测试村")["items"][0]["id"], "n1")
        self.assertEqual(BUILDER.search_index(output, "village")["items"][0]["id"], "n1")
        self.assertEqual(BUILDER.search_index(output, "测试路")["items"][0]["id"], "w11")
        self.assertEqual(BUILDER.search_index(output, "测试市")["items"][0]["id"], "r20")

    def test_changed_source_fails_before_creating_index(self):
        self.source.write_text(fixture())
        with self.assertRaisesRegex(ValueError, "source checksum"):
            BUILDER.build(self.source, self.region, self.root / "places.sqlite")
        self.assertFalse((self.root / "places.sqlite").exists())

    def test_changed_geometry_fails_before_creating_index(self):
        geometry = self.region / "extraction-region.geojson"
        geometry.write_text(json.dumps({"type": "FeatureCollection", "features": []}))
        with self.assertRaisesRegex(ValueError, "region checksum"):
            BUILDER.build(self.source, self.region, self.root / "places.sqlite")

    def test_bad_names_are_counted_and_outside_points_are_excluded(self):
        text = self.source.read_text().replace('v="测试村"', f'v="{"村" * 121}"')
        text = text.replace('<way id="10">', '<node id="99" lat="10" lon="10">'
            '<tag k="name" v="外部地点"/></node><way id="10">')
        self.source.write_text(text)
        self.reprepare()
        output = self.root / "places.sqlite"
        report = BUILDER.build(self.source, self.region, output)
        self.assertEqual(report["place_count"], 2)
        self.assertEqual(report["source"]["skipped"], {"invalid_name": 1})
        self.assertEqual(BUILDER.search_index(output, "外部")["items"], [])

    def test_source_changed_during_scan_does_not_publish(self):
        actual_digest = BUILDER.digest
        calls = 0

        def changed(path):
            nonlocal calls
            if path == self.source:
                calls += 1
                if calls > 1:
                    return "changed"
            return actual_digest(path)

        with patch.object(BUILDER, "digest", changed), self.assertRaisesRegex(ValueError, "Source changed"):
            BUILDER.build(self.source, self.region, self.root / "places.sqlite")
        self.assertFalse((self.root / "places.sqlite").exists())

    def test_cli_outputs_real_index_receipt_and_rejects_existing_output(self):
        output = self.root / "places.sqlite"
        args = ["builder", str(self.source), "--region-directory", str(self.region),
                "--output", str(output)]
        capture = io.StringIO()
        with patch("sys.argv", args), redirect_stdout(capture):
            BUILDER.main()
        self.assertEqual(json.loads(capture.getvalue())["place_count"], 3)
        with self.assertRaises(FileExistsError):
            BUILDER.build(self.source, self.region, output)

    def test_wrong_region_algorithm_is_not_accepted(self):
        path = self.region / "region-manifest.json"
        manifest = json.loads(path.read_text())
        manifest["algorithm_version"] = "unverified"
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "Unverified region"):
            BUILDER.build(self.source, self.region, self.root / "places.sqlite")

    def test_record_limit_is_enforced_during_collection(self):
        with patch.object(BUILDER, "MAX_PLACES", 2), self.assertRaisesRegex(ValueError, "place_count_limit"):
            BUILDER.build(self.source, self.region, self.root / "places.sqlite")
        self.assertFalse((self.root / "places.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
