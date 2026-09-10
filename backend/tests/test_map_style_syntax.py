import json
import subprocess
from types import SimpleNamespace

import pytest

from app.services import map_style_syntax as service


def test_actual_official_validator_accepts_valid_and_rejects_bad_paint():
    style = {'version': 8, 'sources': {}, 'layers': [
        {'id': 'background', 'type': 'background', 'paint': {'background-color': '#14212d'}}]}
    report = service.validate_style_syntax(json.dumps(style).encode())
    assert report['validator'] == '@maplibre/maplibre-gl-style-spec'
    assert report['version']
    style['layers'][0]['paint']['background-color'] = 'not-a-color'
    with pytest.raises(ValueError, match='invalid_style_syntax'):
        service.validate_style_syntax(json.dumps(style).encode())


def test_missing_runtime_fails_closed(monkeypatch):
    monkeypatch.setattr(service.shutil, 'which', lambda _: None)
    with pytest.raises(ValueError, match='style_validator_unavailable'):
        service.validate_style_syntax(b'{}')


@pytest.mark.parametrize('error', [OSError('private path'), subprocess.TimeoutExpired('node', 10)])
def test_timeout_and_launch_failure_are_controlled(monkeypatch, error):
    monkeypatch.setattr(service.shutil, 'which', lambda _: '/trusted/node')
    def fail(*args, **kwargs):
        assert kwargs['env'] == {'PATH': service.os.defpath, 'LANG': 'C.UTF-8'}
        assert kwargs['timeout'] == 10
        assert args[0][0] == '/trusted/node'
        raise error
    monkeypatch.setattr(service.subprocess, 'run', fail)
    with pytest.raises(ValueError, match='style_validator_unavailable'):
        service.validate_style_syntax(b'{}')


@pytest.mark.parametrize('stdout', [b'', b'x' * 1025, b'not-json', b'null', b'[]',
    b'{"status":"style_syntax_validated"}', b'\xff'])
def test_invalid_child_response_cannot_authorize_import(monkeypatch, stdout):
    monkeypatch.setattr(service.shutil, 'which', lambda _: '/trusted/node')
    monkeypatch.setattr(service.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=stdout))
    with pytest.raises(ValueError):
        service.validate_style_syntax(b'{}')


@pytest.mark.parametrize('content', [b'', b'X' * (1024 * 1024 + 1), '{}'],
    ids=['empty', 'oversized', 'not-bytes'])
def test_bounded_input(content):
    with pytest.raises(ValueError, match='invalid_style_size'):
        service.validate_style_syntax(content)
