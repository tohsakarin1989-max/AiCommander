"""Official style syntax check in the isolated map worker, not the core API."""
import json
import os
from pathlib import Path
import shutil
import subprocess


def validate_style_syntax(content: bytes) -> dict:
    if not isinstance(content, bytes) or not 0 < len(content) <= 1024 * 1024:
        raise ValueError('invalid_style_size')
    node = shutil.which('node')
    if node is None:
        raise ValueError('style_validator_unavailable')
    script = Path(__file__).resolve().parents[3] / 'frontend/scripts/validate-map-style.cjs'
    try:
        # Never pass the backend's credentials or NODE_OPTIONS to the child.
        result = subprocess.run([node, '--max-old-space-size=128', str(script)],
            input=content, capture_output=True, timeout=10, check=False,
            env={'PATH': os.defpath, 'LANG': 'C.UTF-8'}, cwd=script.parent)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('style_validator_unavailable') from exc
    if result.returncode != 0 or not 0 < len(result.stdout) <= 1024:
        raise ValueError('invalid_style_syntax')
    try:
        report = json.loads(result.stdout)
    except (UnicodeError, ValueError) as exc:
        raise ValueError('invalid_style_validator_response') from exc
    if (not isinstance(report, dict) or set(report) != {'status', 'validator', 'version'}
            or report['status'] != 'style_syntax_validated'
            or report['validator'] != '@maplibre/maplibre-gl-style-spec'
            or not isinstance(report['version'], str) or not 1 <= len(report['version']) <= 64):
        raise ValueError('invalid_style_validator_response')
    return report
