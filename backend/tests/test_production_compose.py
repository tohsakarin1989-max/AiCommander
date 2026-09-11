"""Exercise shell argument assembly without Docker or production credentials."""
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize('roads,agents', [('false', 'false'), ('true', 'false'), ('true', 'true')])
def test_same_base_override_and_profiles_for_all_deployment_commands(tmp_path, roads, agents):
    root = Path(__file__).resolve().parents[2]
    env_file = tmp_path / 'synthetic config.env'
    env_file.write_text(f'ENABLE_ROAD_ANALYSIS={roads}\nENABLE_AGENT_LAB={agents}\n')
    env = dict(os.environ, ROOT_DIR=str(root), ENV_FILE=str(env_file), COMPOSE_FILE='base config.yml')
    for command in ('config', 'up', 'exec'):
        result = subprocess.run(['sh', '-c',
            '. "$ROOT_DIR/scripts/production-compose.sh"; docker() { printf "%s\\n" "$@"; }; compose "$1"',
            'test', command], env=env, capture_output=True, text=True, check=True)
        args = result.stdout.splitlines()
        assert args[0] == 'compose' and args[-1] == command
        assert args[args.index('--env-file') + 1] == str(env_file)
        files = [args[index + 1] for index, item in enumerate(args) if item == '-f']
        assert files == ['base config.yml'] + ([str(root / 'docker-compose.road-runtime.yml')] if roads == 'true' else [])
        profiles = [args[index + 1] for index, item in enumerate(args) if item == '--profile']
        assert ('road-analysis' in profiles) == (roads == 'true')
        assert ('agent-lab' in profiles) == (agents == 'true')


def test_invalid_road_switch_fails_before_any_docker_call(tmp_path):
    root = Path(__file__).resolve().parents[2]
    config = tmp_path / 'config'
    config.write_text('ENABLE_ROAD_ANALYSIS=maybe\n')
    result = subprocess.run(['sh', '-c',
        '. "$ROOT_DIR/scripts/production-compose.sh"; docker() { echo MUST_NOT_RUN; }; compose config'],
        env=dict(os.environ, ROOT_DIR=str(root), ENV_FILE=str(config), COMPOSE_FILE='base.yml'),
        text=True, capture_output=True)
    assert result.returncode != 0 and 'MUST_NOT_RUN' not in result.stdout
    assert 'ENABLE_ROAD_ANALYSIS' in result.stderr
