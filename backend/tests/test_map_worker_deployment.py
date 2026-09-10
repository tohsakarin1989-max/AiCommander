from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_core_image_excludes_runtime_map_and_business_data():
    ignored = (ROOT / 'backend/.dockerignore').read_text().splitlines()
    assert 'data' in ignored
    assert not any(line.startswith('!data') for line in ignored)
    config = yaml.safe_load((ROOT / 'docker-compose.production.yml').read_text())
    assert 'map_packages:/var/lib/aicommander/maps' in config['services']['backend']['volumes']


def test_map_worker_is_opt_in_and_internally_isolated():
    config = yaml.safe_load((ROOT / 'docker-compose.production.yml').read_text())
    worker = config['services']['map-worker']
    assert worker['profiles'] == ['map-build']
    assert worker['networks'] == ['data']
    assert config['networks']['data']['internal'] is True
    assert not worker.get('ports')
    assert worker['read_only'] is True
    assert worker['cap_drop'] == ['ALL']
    assert worker['security_opt'] == ['no-new-privileges:true']
    assert worker['mem_limit'] == '4g'
    assert worker['cpus'] == 2
    assert worker['pids_limit'] == 128
    assert '--queues=map_build' in worker['command']
    assert '--concurrency=1' in worker['command']
    assert '--prefetch-multiplier=1' in worker['command']
    assert 'map_packages:/var/lib/aicommander/maps' in worker['volumes']
    assert config['services']['backend']['build']['context'] == './backend'


def test_map_build_context_has_no_broad_source_or_secret_copy():
    path = ROOT / 'deploy/map-worker'
    ignored = (path / 'Dockerfile.dockerignore').read_text().splitlines()
    assert ignored[0] == '**'
    assert '!backend/app/**' in ignored
    assert '!frontend/package-lock.json' in ignored
    assert not any(line in ignored for line in ['!backups/**', '!secrets/**', '!backend/**'])
    dockerfile = (path / 'Dockerfile').read_text()
    assert 'COPY . ' not in dockerfile
    assert 'USER 10001:10001' in dockerfile
    assert dockerfile.count('@sha256:') == 2
    assert 'npm ci --omit=dev --ignore-scripts' in dockerfile
