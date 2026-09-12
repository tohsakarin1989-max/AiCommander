"""把已获准下载的本地模型导出为可验包的离线目录；不联网，不修改源模型。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services.local_embedding_service import verify_bundle


def package(source: Path, destination: Path, *, model_id: str, source_revision: str, license_record: str, dimension: int):
    if (not source.is_absolute() or not destination.is_absolute() or source.is_symlink()
            or not source.is_dir() or destination.exists() or not destination.parent.is_dir()
            or destination.resolve().is_relative_to(source.resolve())):
        raise ValueError('invalid_or_existing_bundle_target')
    if not all(value.strip() for value in (model_id, source_revision, license_record)):
        raise ValueError('model_provenance_required')
    # Hidden-state size need not equal final pooling output dimension. Require the contract explicitly.
    if type(dimension) is not int or not 1 <= dimension <= 4096:
        raise ValueError('model_dimension_not_supported')
    with tempfile.TemporaryDirectory(prefix='embedding-package-', dir=destination.parent) as directory:
        temporary = Path(directory)
        files = {}
        for path in source.rglob('*'):
            if path.is_symlink():
                raise ValueError('source_model_contains_symlinks_export_real_files_first')
            if not path.is_file() or path.name == 'embedding-manifest.json':
                continue
            # Safetensors only. Unneeded pickle/ONNX/training artifacts are not copied.
            if path.suffix.lower() not in {'.json', '.txt', '.md', '.model', '.safetensors'}:
                continue
            name = path.relative_to(source).as_posix()
            target = temporary / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            with target.open('rb') as stream:
                files[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
        manifest = {'schema_version': 'local-embedding-bundle-1', 'model_id': model_id,
                    'source_revision': source_revision, 'license_record': license_record,
                    'dimension': dimension, 'files': files}
        raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode()
        digest = hashlib.sha256(raw).hexdigest()
        (temporary / 'embedding-manifest.json').write_bytes(raw)
        verify_bundle(str(temporary), digest)
        if destination.exists():
            raise ValueError('bundle_target_already_exists')
        os.rename(temporary, destination)
    return {'model_id': model_id, 'manifest_sha256': digest, 'files': len(files),
            'dimension': dimension, 'inference_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model-id', required=True)
    parser.add_argument('--source-revision', required=True)
    parser.add_argument('--license-record', required=True)
    parser.add_argument('--dimension', type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.source, args.output, model_id=args.model_id,
                            source_revision=args.source_revision, license_record=args.license_record,
                            dimension=args.dimension), ensure_ascii=False))


if __name__ == '__main__':
    main()
