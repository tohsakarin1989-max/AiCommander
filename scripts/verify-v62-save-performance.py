"""Compare a frozen pre-change source and candidate with isolated synthetic saves.

Supply the source snapshot captured before this implementation. No Git version
is substituted for the dirty local worktree. Reuses the prior fixed workload.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('save_workload', ROOT / 'scripts/verify-v60-save-performance.py')
workload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workload)


def digest(folder):
    result = hashlib.sha256()
    for path in sorted(folder.rglob('*.py')):
        result.update(str(path.relative_to(folder)).encode() + b'\0' + path.read_bytes())
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline-source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline-label', default='pre-v6.2-v6.1-local-source-snapshot')
    args = parser.parse_args()
    baseline = args.baseline_source.resolve(strict=True)
    assert (baseline / 'app/services/case_source_service.py').is_file()
    assert baseline != ROOT / 'backend', 'baseline_must_be_separate_frozen_source'
    rows = []
    with tempfile.TemporaryDirectory(prefix='aic-v62-save-') as directory:
        area = Path(directory)
        frozen = area / 'candidate/app'
        shutil.copytree(ROOT / 'backend/app', frozen, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        hashes = {'baseline': digest(baseline / 'app'), 'candidate': digest(frozen)}
        for index, label in enumerate(('baseline', 'candidate', 'candidate', 'baseline', 'baseline', 'candidate')):
            run_dir = area / f'run-{index}'
            run_dir.mkdir()
            source = baseline if label == 'baseline' else frozen.parent
            environment = {key: os.environ[key] for key in ('PATH', 'LANG', 'TMPDIR') if key in os.environ}
            run = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker', str(source)],
                cwd=run_dir, env=environment, capture_output=True, text=True, timeout=90)
            if run.returncode:
                raise RuntimeError(run.stderr[-3000:])
            rows.append({'label': label, **json.loads(run.stdout.splitlines()[-1])})
            print(json.dumps({'run': index, 'label': label, 'p95_ms': rows[-1]['p95_ms']}), flush=True)
    p95 = {label: {key: workload.percentile([sample for row in rows if row['label'] == label
        for sample in row['samples_ms'][key]]) for key in ('create', 'update')} for label in ('baseline', 'candidate')}
    change = {key: 100 * (p95['candidate'][key] / p95['baseline'][key] - 1) for key in ('create', 'update')}
    value = {'source_hashes': hashes, 'baseline': args.baseline_label,
        'platform': platform.platform(), 'python': sys.version,
        'database': 'fresh-temporary-file-sqlite', 'seed_cases': workload.SEED_CASES,
        'samples_per_operation_per_run': workload.SAMPLES, 'warmup': workload.WARMUP,
        'network_allowed': False, 'http_verified': False, 'target_server_verified': False,
        'comparison_boundary': 'service save latency only; only the named frozen local source baseline',
        'pooled_p95_ms': p95, 'change_percent': change,
        'local_five_percent_target_passed': all(number <= 5 for number in change.values()), 'records': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    print(json.dumps({'report': str(args.output), 'pooled_p95_ms': p95, 'change_percent': change,
        'local_five_percent_target_passed': value['local_five_percent_target_passed']}))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        workload.worker(Path(sys.argv[2]))
    else:
        main()
