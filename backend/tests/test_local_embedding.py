import hashlib
import json
import math
import sys
from types import SimpleNamespace

import pytest

from app.services.local_embedding_service import LocalEmbeddingError, LocalEmbeddingService, normalized_vector, verify_bundle


def bundle(tmp_path, *, dimension=2, modules=None):
    files = {'config.json': '{}', 'model.safetensors': 'synthetic-not-a-real-model',
             'modules.json': json.dumps(modules or [
                 {'idx': 0, 'name': '0', 'path': '', 'type': 'sentence_transformers.models.Transformer'},
                 {'idx': 1, 'name': '1', 'path': '1_Pooling', 'type': 'sentence_transformers.models.Pooling'}])}
    for name, value in files.items():
        (tmp_path / name).write_text(value)
    manifest = {'schema_version': 'local-embedding-bundle-1', 'model_id': 'synthetic-fixture',
                'dimension': dimension, 'files': {name: hashlib.sha256(value.encode()).hexdigest() for name, value in files.items()}}
    raw = json.dumps(manifest).encode()
    (tmp_path / 'embedding-manifest.json').write_bytes(raw)
    return str(tmp_path), hashlib.sha256(raw).hexdigest()


def fake_runtime(monkeypatch):
    captured = {'chunks': []}
    class Tokenizer:
        def encode(self, text, add_special_tokens, truncation):
            assert truncation is False
            return [ord(letter) for letter in text] + ([0, 0] if add_special_tokens else [])
        def num_special_tokens_to_add(self, pair):
            return 2
        def decode(self, values, **kwargs):
            return ''.join(chr(value) for value in values)
    class Model:
        max_seq_length = 8
        tokenizer = Tokenizer()
        def __init__(self, path, **kwargs):
            captured['kwargs'] = kwargs
        def get_sentence_embedding_dimension(self):
            return 2
        def encode(self, chunks, **kwargs):
            captured['chunks'] += chunks
            return [[1.0, 0.0] for _ in chunks]
    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(SentenceTransformer=Model))
    return captured


def test_empty_configuration_does_not_import_or_download(monkeypatch):
    monkeypatch.setitem(sys.modules, 'sentence_transformers', None)
    service = LocalEmbeddingService('', '')
    assert service.state == 'not_enabled'
    with pytest.raises(LocalEmbeddingError, match='not_enabled'):
        service.encode('案情原文')


def test_pinned_local_loader_chunks_entire_text_and_sets_no_remote_options(tmp_path, monkeypatch):
    captured = fake_runtime(monkeypatch)
    service = LocalEmbeddingService(*bundle(tmp_path))
    assert service.state == 'ready'
    assert service.encode('abcdefghijklm') == [1, 0]
    assert ''.join(captured['chunks']) == 'abcdefghijklm'
    assert all(len(chunk) <= 6 for chunk in captured['chunks'])
    assert captured['kwargs']['local_files_only'] is True
    assert captured['kwargs']['trust_remote_code'] is False
    assert captured['kwargs']['token'] is False
    assert captured['kwargs']['model_kwargs']['use_safetensors'] is True


@pytest.mark.parametrize('mutation', ['manifest', 'file', 'extra', 'symlink', 'remote_module', 'module_escape'])
def test_modified_or_executable_bundle_rejected_before_model_import(tmp_path, monkeypatch, mutation):
    modules = None
    if mutation == 'remote_module':
        modules = [{'type': 'evil.module.Call', 'path': ''}]
    if mutation == 'module_escape':
        modules = [{'type': 'sentence_transformers.models.Transformer', 'path': '../outside'}]
    path, digest = bundle(tmp_path, modules=modules)
    if mutation == 'manifest':
        digest = '0' * 64
    elif mutation == 'file':
        (tmp_path / 'config.json').write_text('changed')
    elif mutation == 'extra':
        (tmp_path / 'unexpected.py').write_text('raise RuntimeError()')
    elif mutation == 'symlink':
        (tmp_path / 'link').symlink_to(tmp_path / 'config.json')
    monkeypatch.setitem(sys.modules, 'sentence_transformers', None)
    with pytest.raises(LocalEmbeddingError):
        verify_bundle(path, digest)
    assert LocalEmbeddingService(path, digest).state == 'unavailable'


def test_wrong_dimension_and_input_budget_fail_explicitly(tmp_path, monkeypatch):
    fake_runtime(monkeypatch)
    assert LocalEmbeddingService(*bundle(tmp_path, dimension=3)).error_code == 'embedding_dimension_mismatch'
    service = LocalEmbeddingService(*bundle(tmp_path))
    with pytest.raises(LocalEmbeddingError, match='budget_exceeded'):
        service.encode('油' * 385)


@pytest.mark.parametrize('values', [[0., 0.], [float('nan'), 1.], [float('inf'), 0.], [True, 1.], [1.]])
def test_invalid_vectors_are_not_stored(values):
    with pytest.raises(LocalEmbeddingError):
        normalized_vector(values, 2)


def test_packager_preserves_source_and_refuses_existing_target(tmp_path):
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path
    source = tmp_path / 'source'
    source.mkdir()
    bundle(source)
    (source / 'legacy.bin').write_bytes(b'not copied')
    before = {file.name: file.read_bytes() for file in source.iterdir()}
    script = Path(__file__).resolve().parents[2] / 'scripts/package-local-embedding.py'
    spec = spec_from_file_location('embedding_packager', script)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path / 'export'
    args = dict(model_id='fixture-only', source_revision='fixture-1', license_record='test-only', dimension=2)
    result = module.package(source, target, **args)
    assert result['inference_verified'] is False
    verify_bundle(str(target), result['manifest_sha256'])
    assert not (target / 'legacy.bin').exists()
    assert {file.name: file.read_bytes() for file in source.iterdir()} == before
    with pytest.raises(ValueError, match='existing_bundle_target'):
        module.package(source, target, **args)
