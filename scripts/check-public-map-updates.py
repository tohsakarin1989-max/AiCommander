#!/usr/bin/env python3
"""Public-network-only monthly source metadata check. Never imports the app.

No PBF download, internal data read, map build or publication is performed.
Provider MD5 detects change only; downloaded candidates still require SHA256,
reference/geometry/license checks and the normal controlled map package pipeline.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

REGIONS = ('heilongjiang', 'jilin', 'inner-mongolia')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('provider_redirect_rejected')


def parse_checksum(region, body):
    if region not in REGIONS:
        raise ValueError('unknown_public_region')
    match = re.fullmatch(r'([a-fA-F0-9]{32})\s+\*?' + re.escape(region) + r'-latest\.osm\.pbf\s*',
                         body.decode('ascii'))
    if not match:
        raise ValueError('invalid_provider_checksum')
    return match.group(1).lower()


def fetch(region):
    if region not in REGIONS:
        raise ValueError('unknown_public_region')
    url = f'https://download.geofabrik.de/asia/china/{region}-latest.osm.pbf.md5'
    # Do not inherit a workstation proxy or forward credentials/cookies.
    opener = build_opener(ProxyHandler({}), HTTPSHandler(), NoRedirect())
    with opener.open(Request(url, headers={'User-Agent': 'AiCommander-public-map-check/1'}), timeout=15) as response:
        if response.status != 200:
            raise ValueError('provider_status_invalid')
        body = response.read(2049)
        if len(body) > 2048:
            raise ValueError('provider_response_too_large')
    return parse_checksum(region, body)


def check(previous, now, fetcher=fetch, force=False):
    month = now.astimezone(timezone.utc).strftime('%Y-%m')
    if previous.get('last_success_month') == month and previous.get('status') == 'checked' and not force:
        return None
    entries = {}
    for region in REGIONS:
        old = previous.get('sources', {}).get(region, {}).get('provider_md5')
        try:
            checksum = fetcher(region)
            if not re.fullmatch('[a-f0-9]{32}', checksum):
                raise ValueError('invalid_provider_checksum')
            entries[region] = {'provider_md5': checksum, 'status':
                'initial_candidate' if old is None else 'changed' if old != checksum else 'unchanged',
                'source_url': f'https://download.geofabrik.de/asia/china/{region}-latest.osm.pbf'}
        except Exception as exc:
            entries[region] = {'provider_md5': old, 'status': 'failed', 'error_type': type(exc).__name__}
    success = all(entry['status'] != 'failed' for entry in entries.values())
    return {'schema_version': 1, 'checked_at': now.isoformat(),
            'last_success_month': month if success else previous.get('last_success_month'),
            'status': 'checked' if success else 'degraded', 'sources': entries,
            'map_changed': False, 'downloaded_pbf': False,
            'next_step': 'Build a version-frozen public candidate package through the existing validation pipeline; do not publish these metadata directly.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='Public-only collector state directory, never an internal map store')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    state = args.output_dir / 'public-update-state.json'
    if state.is_symlink():
        raise ValueError('state_symlink_rejected')
    previous = json.loads(state.read_text()) if state.exists() else {}
    now = datetime.now(timezone.utc)
    result = check(previous, now, force=args.force)
    if result is None:
        print('already_checked_this_month')
        return 0
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    # Unique evidence is retained even when a later attempt succeeds.
    with tempfile.NamedTemporaryFile(mode='w', prefix='check-', suffix='.json',
                                     dir=args.output_dir, delete=False) as evidence:
        evidence.write(encoded)
        evidence_path = evidence.name
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', prefix='.state-', dir=args.output_dir, delete=False) as target:
            temporary = target.name
            target.write(encoded)
        os.replace(temporary, state)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink()
    print(json.dumps({'status': result['status'], 'evidence': evidence_path,
                      'sources': {name: item['status'] for name, item in result['sources'].items()}}))
    return 0 if result['status'] == 'checked' else 1


if __name__ == '__main__':
    raise SystemExit(main())
