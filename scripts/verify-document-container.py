"""Run the synthetic export check in an offline, read-only candidate container."""
import json
import os
from pathlib import Path
import subprocess
import re


def main():
    if os.environ.get('AIC_DISPOSABLE_RENDER_CHECK') != '1':
        raise RuntimeError('explicit_disposable_check_required')
    source = Path(__file__).resolve().parents[1] / 'backend/document-renderer/check-runtime.py'
    image = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}',
                            'aicommander-backend-documents:v4.1-candidate'],
                           check=True, capture_output=True, text=True, timeout=15).stdout.strip()
    command = ['docker', 'create', '--network', 'none', '--read-only',
               '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--init',
               '--memory', '2g', '--cpus', '2', '--pids-limit', '256',
               '--tmpfs', '/tmp:size=768m,mode=1777', '--shm-size', '256m',
               '--mount', f'type=bind,source={source},target=/app/document-renderer/check-runtime.py,readonly',
               '-e', 'AIC_DISPOSABLE_RENDER_CHECK=1', '-e', 'SECRET_KEY=synthetic-offline-export-only',
               '-e', 'ENVIRONMENT=development', '-e', 'ENABLE_VECTOR_DB=false',
               '--entrypoint', 'python', image, '/app/document-renderer/check-runtime.py']
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
