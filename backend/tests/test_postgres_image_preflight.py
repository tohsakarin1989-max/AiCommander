"""Preflight must not pull or touch existing database volumes."""
import os
from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/check-postgres-image.sh'


@pytest.mark.parametrize('reference', ['', 'postgis:latest', 'sha256:bad', 'sha256:' + 'z' * 64])
def test_invalid_reference_fails_before_docker(reference, tmp_path):
    result = subprocess.run(['/bin/sh', str(SCRIPT), reference], env={'PATH': str(tmp_path)},
                            text=True, capture_output=True)
    assert result.returncode != 0
    assert 'sha256' in result.stderr or '摘要' in result.stderr


@pytest.mark.parametrize('installed,capable', [(False, False), (True, False), (True, True)])
def test_inspect_then_read_only_extension_probe(tmp_path, installed, capable):
    calls = tmp_path / 'calls'
    fake = tmp_path / 'docker'
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$PROBE_CALLS"\n'
        f'if [ "$1" = image ]; then exit {0 if installed else 1}; fi\n'
        f'exit {0 if capable else 1}\n')
    fake.chmod(0o700)
    result = subprocess.run(['/bin/sh', str(SCRIPT), 'sha256:' + 'a' * 64],
        env={**os.environ, 'PATH': str(tmp_path), 'PROBE_CALLS': str(calls)}, capture_output=True)
    assert (result.returncode == 0) == (installed and capable)
    log = calls.read_text()
    if installed:
        assert '--network none --read-only' in log and '--pull=never' in log
        assert 'postgis.control' in log and 'vector.control' in log
        assert '--volume' not in log and ' -v ' not in log
    else:
        assert 'run ' not in log
