"""CLI failure boundaries; actual glyph decoding is a separate artifact check."""
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / 'generate-map-glyphs.cjs'


class GlyphGeneratorTests(unittest.TestCase):
    def test_incomplete_composite_arguments_are_rejected(self):
        result = subprocess.run(['node', str(SCRIPT), '/missing', '/font', '/output',
                                 '/mongolian'], capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'Usage:', result.stderr)

    def test_composite_mode_checks_inputs_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sdfglyph.js').write_text('must not execute')
            output = root / 'output'
            result = subprocess.run(['node', str(SCRIPT), str(root), '/font', str(output),
                                     '/mongolian', '/emoji'], capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'checksum', result.stderr)
            self.assertFalse(output.exists())

    def test_requires_arguments(self):
        result = subprocess.run(['node', str(SCRIPT)], capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'Usage:', result.stderr)

    def test_changed_tool_rejected_without_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sdfglyph.js').write_text('throw new Error("must not execute")')
            (root / 'sdfglyph.wasm').write_bytes(b'wrong')
            (root / 'font.otf').write_bytes(b'wrong')
            output = root / 'output'
            result = subprocess.run(['node', str(SCRIPT), str(root), str(root / 'font.otf'),
                                     str(output)], capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'checksum', result.stderr)
            self.assertFalse(output.exists())

    def test_existing_output_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'output'
            output.mkdir()
            (output / 'sentinel').write_text('retain')
            result = subprocess.run(['node', str(SCRIPT), str(root), str(root / 'font.otf'),
                                     str(output)], capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((output / 'sentinel').read_text(), 'retain')
