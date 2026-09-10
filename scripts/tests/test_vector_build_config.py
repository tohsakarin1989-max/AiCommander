import json
import unittest
from pathlib import Path


class VectorBuildConfigTests(unittest.TestCase):
    def test_candidate_has_native_6_to_16_and_no_network_resources(self):
        config = json.loads((Path(__file__).parents[1] /
                             "map-build/two-city-vector.json").read_text())
        self.assertEqual(config["settings"]["minzoom"], 6)
        self.assertEqual(config["settings"]["maxzoom"], 16)
        self.assertEqual(config["settings"]["basezoom"], 16)
        self.assertTrue(config["settings"]["include_ids"])
        self.assertTrue(all(layer["maxzoom"] == 16 for layer in config["layers"].values()))
        self.assertFalse(any("source" in layer for layer in config["layers"].values()))
        self.assertNotIn("tiles", config["settings"].get("filemetadata", {}))
        for layer in ("transportation", "building", "water", "place", "boundary"):
            self.assertIn(layer, config["layers"])
        west, south, east, north = config["settings"]["bounding_box"]
        self.assertLessEqual(west, 122.3923608)
        self.assertLessEqual(south, 45.3802435)
        self.assertGreaterEqual(east, 126.6607166)
        self.assertGreaterEqual(north, 48.9215877)


if __name__ == "__main__":
    unittest.main()
