"""Two-city public maps and synthetic cases in separate offline test containers."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    if os.environ.get('AIC_DISPOSABLE_RENDER_CHECK') != '1':
        raise RuntimeError('explicit_disposable_check_required')
    root = Path(__file__).resolve().parents[1]
    relative = 'backups/map-foundation/v4-source/20260908/complete-candidate-v2/map-assembly-muyp0orr'
    assert (root / relative).is_dir(), 'fixed_public_assets_required'
    image = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}',
                            'aicommander-document-check:v4.1-candidate'],
                           check=True, capture_output=True, text=True, timeout=15).stdout.strip()
    (root / 'output').mkdir(exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='v41-container-map-export-', dir=root / 'output'))
    for city in ('daqing', 'qiqihar'):
        evidence = output / city
        evidence.mkdir(mode=0o777)
        evidence.chmod(0o777)  # New synthetic-only output, writable by container UID10001.
        args = ['docker', 'create', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--init', '--memory', '2g', '--cpus', '2',
                '--pids-limit', '256', '--tmpfs', '/tmp:size=768m,mode=1777', '--shm-size', '256m',
                '--mount', f'type=bind,source={root / "backend/tests"},target=/checks/backend/tests,readonly',
                '--mount', f'type=bind,source={root / relative},target=/checks/{relative},readonly',
                '--mount', f'type=bind,source={evidence},target=/evidence',
                '-e', 'SECRET_KEY=synthetic-map-export-only', '-e', 'ENVIRONMENT=development',
                '-e', 'ENABLE_VECTOR_DB=false', '-e', 'PYTHONPATH=/app:/checks/backend:/checks/backend/tests',
                '-e', 'AIC_TEST_REAL_VECTOR_MAP=1', '-e', 'AIC_TEST_PDF_OFFICE=1',
                '-e', 'AIC_RENDER_EVIDENCE_DIR=/evidence', '--entrypoint', 'python', image,
                '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '--basetemp=/tmp/export-check',
                f'/checks/backend/tests/test_case_vector_map_image.py::test_real_two_city_vector_map_and_chinese_glyphs_in_word[{city}]']
        container = subprocess.run(args, check=True, capture_output=True, text=True, timeout=30).stdout.strip()
        if not re.fullmatch(r'[a-f0-9]{64}', container):
            raise RuntimeError('unexpected_container_id')
        try:
            result = subprocess.run(['docker', 'start', '-a', container], capture_output=True, text=True, timeout=180)
            print(result.stdout, flush=True)
            if result.returncode:
                print(result.stderr, flush=True)
                result.check_returncode()
        finally:
            subprocess.run(['docker', 'rm', '-f', container], check=True, capture_output=True, timeout=15)
        print(json.dumps({'city': city, 'image_id': image, 'evidence': str(evidence),
                          'network': 'none', 'synthetic_cases': True}), flush=True)


if __name__ == '__main__':
    main()
