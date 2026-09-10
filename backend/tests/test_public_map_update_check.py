import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('public_update',
    Path(__file__).resolve().parents[2] / 'scripts/check-public-map-updates.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)


def test_initial_changed_unchanged_and_monthly_skip():
    initial = module.check({}, NOW, lambda _: 'a' * 32)
    assert all(item['status'] == 'initial_candidate' for item in initial['sources'].values())
    assert module.check(initial, NOW, lambda _: pytest.fail('must not fetch twice')) is None
    updated = module.check(initial, datetime(2026, 10, 1, tzinfo=timezone.utc),
                           lambda region: ('b' if region == 'jilin' else 'a') * 32)
    assert updated['sources']['jilin']['status'] == 'changed'
    assert updated['sources']['heilongjiang']['status'] == 'unchanged'
    assert updated['map_changed'] is False and updated['downloaded_pbf'] is False


def test_failure_preserves_last_digest_and_allows_retry():
    old = module.check({}, datetime(2026, 8, 1, tzinfo=timezone.utc), lambda _: 'a' * 32)
    def failed(region):
        if region == 'jilin':
            raise TimeoutError('do not expose endpoint or credentials')
        return 'b' * 32
    result = module.check(old, NOW, failed)
    assert result['status'] == 'degraded'
    assert result['last_success_month'] == '2026-08'
    assert result['sources']['jilin'] == {'provider_md5': 'a' * 32, 'status': 'failed', 'error_type': 'TimeoutError'}
    assert module.check(result, NOW, lambda _: 'b' * 32)['status'] == 'checked'


@pytest.mark.parametrize('body', [b'bad', b'a'*32+b' other.osm.pbf', b'a'*32+b' jilin-latest.osm.pbf extra'])
def test_wrong_filename_or_body_is_rejected(body):
    with pytest.raises(ValueError):
        module.parse_checksum('jilin', body)


def test_redirect_and_unknown_region_rejected():
    with pytest.raises(ValueError):
        module.NoRedirect().redirect_request(None, None, 302, '', {}, 'http://localhost')
    with pytest.raises(ValueError):
        module.fetch('arbitrary-url')
    assert module.parse_checksum('jilin', b'A'*32+b'  jilin-latest.osm.pbf\n') == 'a'*32


def test_forced_failure_in_successful_month_does_not_suppress_retry():
    initial = module.check({}, NOW, lambda _: 'a' * 32)
    def unavailable(_):
        raise TimeoutError()
    failed = module.check(initial, NOW, unavailable, force=True)
    assert failed['status'] == 'degraded' and failed['last_success_month'] == '2026-09'
    retried = module.check(failed, NOW, lambda _: 'b' * 32)
    assert retried['status'] == 'checked'
    assert all(item['status'] == 'changed' for item in retried['sources'].values())


def test_timer_and_deduplication_use_same_utc_month():
    timer = (Path(__file__).resolve().parents[2] /
             'deploy/public-map-updates/aicommander-public-map-check.timer').read_text()
    assert 'OnCalendar=*-*-01 00:00:00 UTC' in timer
