#!/usr/bin/env python3
"""Freeze a stable baseline/current sources and compare identical save workloads.

No business DB, model, network or Git writes. Both arms use idempotent create
and strict revision-aware edit; preparation GET is excluded equally.
"""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ORDER = ('baseline', 'candidate', 'candidate', 'baseline', 'baseline', 'candidate')


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker-backend', type=Path)
    parser.add_argument('--label', choices=('baseline', 'candidate'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline-ref', default='v7.5.0-stable')
    parser.add_argument('--candidate-label', default='8.x working source')
    args = parser.parse_args()
    worker = load('verify-v70-save-performance')
    if args.worker_backend:
        worker.worker(args.worker_backend, args.label, args.output, use_creation_key=True,
                      strict_edit=True, prepare_edit=True, verify_audits=True)
        return
    reference = subprocess.check_output(['git', 'rev-parse', f'{args.baseline_ref}^{{commit}}'], cwd=ROOT, text=True).strip()
    version = subprocess.check_output(['git', 'show', f'{reference}:VERSION'], cwd=ROOT, text=True).strip()
    if version != args.baseline_ref.removeprefix('v'):
        raise ValueError('baseline_version_mismatch')
    result_root = args.output.resolve()
    result_root.mkdir(parents=True, exist_ok=True)
    results = Path(tempfile.mkdtemp(prefix='run-', dir=result_root))
    with tempfile.TemporaryDirectory(prefix='aic-v8-save-') as temporary:
        frozen = Path(temporary)
        raw = subprocess.check_output(['git', 'archive', reference, 'backend/app', 'VERSION'], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            archive.extractall(frozen / 'baseline', filter='data')
        shutil.copytree(ROOT / 'backend/app', frozen / 'candidate/backend/app',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copy2(ROOT / 'VERSION', frozen / 'candidate/VERSION')
        scripts = frozen / 'scripts'
        scripts.mkdir()
        for name in ('verify-v8-save-performance.py', 'verify-v70-save-performance.py', 'verify-v71-save-performance.py'):
            shutil.copy2(Path(__file__).with_name(name), scripts / name)
        metadata = {'baseline_commit': reference, 'baseline_version': version, 'candidate_label': args.candidate_label,
            'source_hashes': {label: worker.digest(frozen / label / 'backend/app') for label in ('baseline', 'candidate')},
            'platform': platform.platform(), 'python': sys.version, 'database': 'fresh-synthetic-SQLite',
            'seed_cases': worker.SEED_CASES, 'warmup': worker.WARMUP, 'samples_per_run': worker.SAMPLES,
            'order': ORDER, 'protocol': 'both idempotent create and strict edit; preparation excluded',
            'input_sha256': hashlib.sha256(json.dumps([worker.CREATE_PAYLOAD, worker.UPDATE_PAYLOAD], sort_keys=True).encode()).hexdigest(),
            'network_allowed': False, 'target_server_verified': False, 'threshold_percent': 5}
        worker.write_json(results / 'metadata.json', metadata)
        with tarfile.open(results / 'frozen-sources.tar.gz', 'w:gz') as archive:
            for folder in ('baseline', 'candidate', 'scripts'):
                archive.add(frozen / folder, arcname=folder)
        print(json.dumps({'evidence_directory': str(results)}), flush=True)
        rows = []
        for index, label in enumerate(ORDER):
            output = results / f'{index}-{label}.json'
            with (results / f'{index}-{label}.log').open('w') as log:
                subprocess.run([sys.executable, str(scripts / 'verify-v8-save-performance.py'),
                    '--worker-backend', str(frozen / label / 'backend'), '--label', label,
                    '--output', str(output)], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
            rows.append({'label': label, **json.loads(output.read_text())})
            print(json.dumps({'finished_run': index, 'label': label}), flush=True)
        summary = load('verify-v71-save-performance').summarize(worker, rows)
        worker.write_json(results / 'summary.json', summary)
        print(json.dumps(summary), flush=True)
        if not summary['local_five_percent_target_passed']:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
