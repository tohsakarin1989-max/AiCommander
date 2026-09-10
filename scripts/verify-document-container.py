"""Run the synthetic export check in an offline, read-only candidate container."""
import json
import os
from pathlib import Path
import subprocess
import re
import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', default='aicommander-backend-documents:v4.1-candidate')
    parser.add_argument('--embedded', action='store_true', help='Run the check shipped inside the image without a host mount')
    parser.add_argument('--core', action='store_true', help='Verify migrations and authenticated case APIs instead of export smoke')
    args = parser.parse_args()
    if os.environ.get('AIC_DISPOSABLE_RENDER_CHECK') != '1':
        raise RuntimeError('explicit_disposable_check_required')
    source = Path(__file__).resolve().parents[1] / 'backend/document-renderer/check-runtime.py'
    target = '/app/document-renderer/check-runtime.py'
    if args.core:
        if args.embedded:
            parser.error('--core uses a read-only verification script; do not combine with --embedded')
        source = Path(__file__).resolve().parent / 'verify-core-image.py'
        target = '/checks/verify-core-image.py'
    image = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}',
                            args.image],
                           check=True, capture_output=True, text=True, timeout=15).stdout.strip()
    command = ['docker', 'create', '--network', 'none', '--read-only',
               '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--init',
               '--memory', '2g', '--cpus', '2', '--pids-limit', '256',
               '--tmpfs', '/tmp:size=768m,mode=1777', '--shm-size', '256m',
               *([] if args.embedded else ['--mount', f'type=bind,source={source},target={target},readonly']),
               '-e', 'AIC_DISPOSABLE_RENDER_CHECK=1', '-e', 'SECRET_KEY=synthetic-offline-export-only',
               '-e', 'ENVIRONMENT=development', '-e', 'ENABLE_VECTOR_DB=false',
               '-e', 'PYTHONPATH=/app', '--entrypoint', 'python', image, target]
    # Keep the exact newly created ID so timeouts also clean up the container.
    container = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30).stdout.strip()
    if not re.fullmatch(r'[a-f0-9]{64}', container):
        raise RuntimeError('unexpected_container_id')
    try:
        result = subprocess.run(['docker', 'start', '-a', container], capture_output=True, text=True, timeout=100)
        print(result.stdout)
        if result.returncode:
            print(result.stderr)
            result.check_returncode()
    finally:
        subprocess.run(['docker', 'rm', '-f', container], check=True, capture_output=True, timeout=15)
    print(json.dumps({'image_id': image, 'network': 'none', 'readonly_root': True,
                      'memory_limit': '2g', 'synthetic_only': True}))


if __name__ == '__main__':
    main()
