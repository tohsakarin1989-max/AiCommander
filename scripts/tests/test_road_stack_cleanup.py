"""Disposable stack cleanup must include opt-in workers and prove no leftovers."""
import importlib.util
from pathlib import Path
import subprocess

import pytest


SPEC = importlib.util.spec_from_file_location(
    'verify_road_stack', Path(__file__).parents[1] / 'verify-road-stack.py',
)
STACK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STACK)
PROJECT = 'aic-road-stack-123456abcdef'


def test_explicit_disposable_networks_preserve_three_separate_private_segments():
    assert STACK.isolated_networks(None) == {}
    networks = STACK.isolated_networks('10.253.240.0/22')
    assert {name: settings['ipam']['config'][0]['subnet']
            for name, settings in networks.items()} == {
                'data': '10.253.240.0/24', 'app': '10.253.241.0/24',
                'edge': '10.253.242.0/24',
            }


@pytest.mark.parametrize('cidr', ['8.8.8.0/22', '127.0.0.0/22', '10.0.0.0/8',
                                  '::/22', 'not-a-network'])
def test_explicit_disposable_networks_reject_invalid_or_non_private_ranges(cidr):
    with pytest.raises(ValueError):
        STACK.isolated_networks(cidr)


def test_cleanup_removes_profile_workers_and_checks_only_owned_resources(monkeypatch):
    resources = {'core': True, 'agent-lab': True, 'unrelated-project': True}
    checked = []

    def compose(*args, timeout):
        assert timeout == 120
        assert args[-3:] == ('down', '--volumes', '--remove-orphans')
        resources['core'] = False
        if args[:2] == ('--profile', '*'):
            resources['agent-lab'] = False

    def inspect(command, **kwargs):
        assert command[-2:] == ['--filter', f'label=com.docker.compose.project={PROJECT}']
        assert kwargs['check'] is True
        checked.append(command[1])
        return subprocess.CompletedProcess(command, 0, 'agent-worker\n' if resources['agent-lab'] else '', '')

    monkeypatch.setattr(STACK.subprocess, 'run', inspect)
    STACK.remove_owned_stack(PROJECT, compose)
    assert checked == ['ps', 'volume', 'network']
    assert resources == {'core': False, 'agent-lab': False, 'unrelated-project': True}


@pytest.mark.parametrize('resource', ['ps', 'volume', 'network'])
def test_cleanup_rejects_any_remaining_project_resource(monkeypatch, resource):
    def inspect(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, 'remaining-id\n' if command[1] == resource else '', '')

    monkeypatch.setattr(STACK.subprocess, 'run', inspect)
    with pytest.raises(RuntimeError, match='owned_stack_resources_remaining'):
        STACK.remove_owned_stack(PROJECT, lambda *args, **kwargs: None)


def test_cleanup_does_not_treat_failed_docker_inspection_as_empty(monkeypatch):
    def inspect(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr='Docker unavailable')

    monkeypatch.setattr(STACK.subprocess, 'run', inspect)
    with pytest.raises(subprocess.CalledProcessError):
        STACK.remove_owned_stack(PROJECT, lambda *args, **kwargs: None)


def test_cleanup_rejects_non_disposable_project_before_any_command():
    def unexpected_command(*args, **kwargs):
        pytest.fail('cleanup ran for a non-disposable project')

    with pytest.raises(ValueError, match='invalid_disposable_stack_project'):
        STACK.remove_owned_stack('aicommander', unexpected_command)


def test_cleanup_propagates_compose_failure_before_inspection(monkeypatch):
    def failed_compose(*args, **kwargs):
        raise RuntimeError('compose_down_failed')

    monkeypatch.setattr(STACK.subprocess, 'run', lambda *args, **kwargs: pytest.fail('unexpected inspection'))
    with pytest.raises(RuntimeError, match='compose_down_failed'):
        STACK.remove_owned_stack(PROJECT, failed_compose)
