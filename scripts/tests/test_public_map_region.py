"""Run with the isolated map-build Python, not the production backend."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "public_map_region", Path(__file__).parents[1] / "prepare-public-map-region.py"
)
REGION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REGION)


def fixture(closed=True):
    end = 1 if closed else 3
    return f'''<osm version="0.6">
      <node id="1" lat="46" lon="124"/>
      <node id="2" lat="46" lon="124.01"/>
      <node id="3" lat="46.01" lon="124.01"/>
      <node id="4" lat="46.01" lon="124"/>
      <way id="10"><nd ref="1"/><nd ref="2"/><nd ref="3"/>
        <nd ref="4"/><nd ref="{end}"/></way>
      <relation id="20"><member type="way" ref="10" role="outer"/>
        <tag k="type" v="boundary"/><tag k="boundary" v="administrative"/>
        <tag k="admin_level" v="5"/><tag k="name" v="测试市"/>
        <tag k="ref:admin:CN" v="000001"/></relation>
    </osm>'''


class PublicRegionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "public.osm"
        self.source.write_text(fixture())
        self.targets = {20: {"name": "测试市", "admin_code": "000001"}}

    def tearDown(self):
        self.temp.cleanup()

    def test_real_osm_boundary_export_preserves_source_and_creates_valid_margin(self):
        result = REGION.prepare(self.source, self.root / "out", 30, self.targets)
        self.assertEqual(result["status"], "region_prepared_not_published")
        self.assertFalse(result["cross_source_coverage_verified"])
        boundaries = json.loads((self.root / "out/city-boundaries.geojson").read_text())
        self.assertEqual(boundaries["features"][0]["properties"]["osm_relation_id"], 20)
        self.assertEqual(result["source"]["bytes"], self.source.stat().st_size)
        bbox = result["extraction_bbox"]
        self.assertLess(bbox[0], 124)
        self.assertGreater(bbox[2], 124.01)
        self.assertGreater(bbox[3], 46.01)

    def test_unknown_boundary_fails_without_success_manifest(self):
        with self.assertRaisesRegex(ValueError, "Missing"):
            REGION.prepare(self.source, self.root / "out", 30, {99: self.targets[20]})
        self.assertFalse((self.root / "out/region-manifest.json").exists())

    def test_open_boundary_cannot_be_silently_repaired(self):
        self.source.write_text(fixture(closed=False))
        with self.assertRaises(ValueError):
            REGION.prepare(self.source, self.root / "out", 30, self.targets)
        self.assertFalse((self.root / "out/region-manifest.json").exists())

    def test_wrong_admin_identity_is_not_accepted_by_id_alone(self):
        with self.assertRaisesRegex(ValueError, "identity"):
            REGION.prepare(self.source, self.root / "out", 30,
                           {20: {"name": "另一城市", "admin_code": "000002"}})

    def test_existing_output_is_not_overwritten(self):
        output = self.root / "out"
        output.mkdir()
        marker = output / "keep.txt"
        marker.write_text("previous")
        with self.assertRaises(FileExistsError):
            REGION.prepare(self.source, output, 30, self.targets)
        self.assertEqual(marker.read_text(), "previous")

    def test_invalid_margin_fails_before_writing(self):
        for margin in (0, -1, 501, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                REGION.prepare(self.source, self.root / "out", margin, self.targets)
        self.assertFalse((self.root / "out").exists())

    def test_nested_geometry_members_are_rejected_even_when_relation_exists(self):
        for exists in (False, True):
            original = fixture().replace('<relation id="20">',
                '<relation id="20"><member type="relation" ref="99" role="outer"/>')
            if exists:
                original = original.replace('</osm>', '<relation id="99"/></osm>')
            self.source.write_text(original)
            output = self.root / f"nested-{exists}"
            with self.assertRaisesRegex(ValueError, "Nested geometry"):
                REGION.prepare(self.source, output, 30, self.targets)
            self.assertFalse((output / "region-manifest.json").exists())

    def test_subarea_is_not_outline_but_must_exist(self):
        original = fixture().replace('<relation id="20">',
            '<relation id="20"><member type="relation" ref="99" role="subarea"/>')
        self.source.write_text(original)
        with self.assertRaisesRegex(ValueError, "Missing boundary member"):
            REGION.prepare(self.source, self.root / "missing-subarea", 30, self.targets)
        self.source.write_text(original.replace('</osm>', '<relation id="99"/></osm>'))
        result = REGION.prepare(self.source, self.root / "present-subarea", 30, self.targets)
        self.assertEqual(result["status"], "region_prepared_not_published")

    def test_disconnected_outer_ring_is_preserved_not_replaced_by_bbox(self):
        text = fixture().replace('<way id="10">', '''
          <node id="5" lat="46.1" lon="124.1"/>
          <node id="6" lat="46.1" lon="124.11"/>
          <node id="7" lat="46.11" lon="124.11"/>
          <node id="8" lat="46.11" lon="124.1"/>
          <way id="10">''')
        text = text.replace('<relation id="20">', '''
          <way id="11"><nd ref="5"/><nd ref="6"/><nd ref="7"/>
            <nd ref="8"/><nd ref="5"/></way>
          <relation id="20"><member type="way" ref="11" role="outer"/>''')
        self.source.write_text(text)
        features = REGION.city_features(self.source, self.targets)
        self.assertEqual(len(features[0]["geometry"]["coordinates"]), 2)

    def test_missing_label_and_unknown_node_role_fail(self):
        for role, message in (("label", "Missing boundary member nodes"),
                              ("outer", "Unsupported boundary node role")):
            self.source.write_text(fixture().replace('<relation id="20">',
                f'<relation id="20"><member type="node" ref="99" role="{role}"/>'))
            with self.assertRaisesRegex(ValueError, message):
                REGION.city_features(self.source, self.targets)


if __name__ == "__main__":
    unittest.main()
