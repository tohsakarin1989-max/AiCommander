"""仅加载批准的离线模型包；不按 Hub 名称下载，不接收网络地址。"""
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
from threading import Lock


class LocalEmbeddingError(ValueError):
    pass


def normalized_vector(values, dimension):
    if hasattr(values, 'tolist'):
        values = values.tolist()
    if (not isinstance(values, list) or len(values) != dimension
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in values)):
        raise LocalEmbeddingError('embedding_invalid_vector')
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or norm < 1e-12:
        raise LocalEmbeddingError('embedding_invalid_vector')
    return [value / norm for value in values]


def verify_bundle(directory: str, expected_digest: str) -> tuple[Path, dict]:
    """固定 manifest + 每个模型文件摘要，拒绝越界、符号链接与可执行模型模块。"""
    path = Path(directory)
    if not path.is_absolute() or not re.fullmatch(r'[0-9a-f]{64}', expected_digest):
        raise LocalEmbeddingError('embedding_bundle_not_pinned')
    if path.is_symlink() or not path.is_dir():
        raise LocalEmbeddingError('embedding_bundle_missing')
    root = path.resolve(strict=True)
    manifest_path = root / 'embedding-manifest.json'
    if manifest_path.is_symlink() or manifest_path.stat().st_size > 1_048_576:
        raise LocalEmbeddingError('embedding_manifest_invalid')
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise LocalEmbeddingError('embedding_manifest_mismatch')
    manifest = json.loads(raw)
    if (not isinstance(manifest, dict) or manifest.get('schema_version') != 'local-embedding-bundle-1'
            or not isinstance(manifest.get('model_id'), str) or not manifest['model_id'].strip()
            or type(manifest.get('dimension')) is not int or not 1 <= manifest['dimension'] <= 4096
            or not isinstance(manifest.get('files'), dict) or not manifest['files']):
        raise LocalEmbeddingError('embedding_manifest_invalid')
    expected = set(manifest['files'])
    if not {'modules.json', 'config.json'}.issubset(expected) or not any(name.endswith('.safetensors') for name in expected):
        raise LocalEmbeddingError('embedding_bundle_incomplete')
    actual = set()
    for file in root.rglob('*'):
        if file.is_symlink():
            raise LocalEmbeddingError('embedding_bundle_link_forbidden')
        if file.is_file() and file.name != 'embedding-manifest.json':
            actual.add(file.relative_to(root).as_posix())
    if actual != expected:
        raise LocalEmbeddingError('embedding_bundle_inventory_mismatch')
    for name, digest in manifest['files'].items():
        relative = PurePosixPath(name)
        if (relative.is_absolute() or '..' in relative.parts or '\\' in name
                or relative.suffix in {'.py', '.pyc', '.pkl', '.pickle', '.pt', '.bin'}
                or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)):
            raise LocalEmbeddingError('embedding_bundle_file_forbidden')
        file = root / name
        if not file.resolve(strict=True).is_relative_to(root):
            raise LocalEmbeddingError('embedding_bundle_path_forbidden')
        with file.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise LocalEmbeddingError('embedding_bundle_hash_mismatch')
    modules = json.loads((root / 'modules.json').read_text())
    allowed = {'sentence_transformers.models.Transformer', 'sentence_transformers.models.Pooling',
               'sentence_transformers.models.Normalize'}
    if (not isinstance(modules, list) or not modules
            or any(not isinstance(module, dict) or module.get('type') not in allowed for module in modules)):
        raise LocalEmbeddingError('embedding_custom_module_forbidden')
    for module in modules:
        module_path = module.get('path', '')
        if (not isinstance(module_path, str) or PurePosixPath(module_path).is_absolute()
                or '..' in PurePosixPath(module_path).parts or '\\' in module_path):
            raise LocalEmbeddingError('embedding_module_path_forbidden')
    return root, manifest


class LocalEmbeddingService:
    """CPU 离线执行，长文本按 token 分块后加权归一化，不无声截断。"""
    def __init__(self, directory: str, manifest_digest: str):
        self.state = 'not_enabled'
        self.error_code = None
        self.model_version = None
        self.dimension = None
        self._model = None
        self._lock = Lock()
        if not directory and not manifest_digest:
            return
        try:
            root, manifest = verify_bundle(directory, manifest_digest)
            # Must be set before importing Hub/Transformers; this runtime is explicitly offline.
            os.environ['HF_HUB_OFFLINE'] = '1'
            os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
            os.environ['TRANSFORMERS_OFFLINE'] = '1'
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(str(root), local_files_only=True, trust_remote_code=False,
                token=False, device='cpu', backend='torch',
                model_kwargs={'use_safetensors': True, 'local_files_only': True, 'trust_remote_code': False})
            if model.get_sentence_embedding_dimension() != manifest['dimension']:
                raise LocalEmbeddingError('embedding_dimension_mismatch')
            if type(model.max_seq_length) is not int or not 8 <= model.max_seq_length <= 8192:
                raise LocalEmbeddingError('embedding_token_limit_invalid')
            self._model = model
            self.dimension = manifest['dimension']
            self.model_version = f'local-token-mean-1:{manifest_digest}'
            self.state = 'ready'
        except LocalEmbeddingError as error:
            self.state, self.error_code = 'unavailable', str(error)
        except Exception:
            # Never expose raw library errors, model paths, tokens or input text.
            self.state, self.error_code = 'unavailable', 'embedding_bundle_unavailable'

    def encode(self, text: str) -> list[float]:
        if self.state != 'ready':
            raise LocalEmbeddingError(self.error_code or 'embedding_not_enabled')
        if not isinstance(text, str) or not text.strip() or len(text) > 1_000_000:
            raise LocalEmbeddingError('embedding_text_invalid')
        try:
            with self._lock:
                tokenizer = self._model.tokenizer
                tokens = tokenizer.encode(text, add_special_tokens=False, truncation=False)
                budget = self._model.max_seq_length - tokenizer.num_special_tokens_to_add(pair=False)
                if budget <= 0 or not tokens or len(tokens) > budget * 64:
                    raise LocalEmbeddingError('embedding_text_budget_exceeded')
                chunks, weights = [], []
                for offset in range(0, len(tokens), budget):
                    part = tokens[offset:offset + budget]
                    chunk = tokenizer.decode(part, skip_special_tokens=True, clean_up_tokenization_spaces=False)
                    if len(tokenizer.encode(chunk, add_special_tokens=True, truncation=False)) > self._model.max_seq_length:
                        raise LocalEmbeddingError('embedding_chunk_overflow')
                    chunks.append(chunk)
                    weights.append(len(part))
                vectors = self._model.encode(chunks, batch_size=8, show_progress_bar=False,
                    convert_to_numpy=True, normalize_embeddings=True)
                if len(vectors) != len(chunks):
                    raise LocalEmbeddingError('embedding_invalid_batch')
                normalized = [normalized_vector(vector, self.dimension) for vector in vectors]
                pooled = [sum(vector[index] * weight for vector, weight in zip(normalized, weights)) / sum(weights)
                          for index in range(self.dimension)]
                return normalized_vector(pooled, self.dimension)
        except LocalEmbeddingError:
            raise
        except Exception:
            raise LocalEmbeddingError('embedding_inference_unavailable') from None


@lru_cache(maxsize=1)
def _configured(directory: str, digest: str):
    return LocalEmbeddingService(directory, digest)


def get_local_embedder() -> LocalEmbeddingService:
    from app.config import settings
    return _configured(settings.LOCAL_EMBEDDING_BUNDLE, settings.LOCAL_EMBEDDING_MANIFEST_SHA256)
