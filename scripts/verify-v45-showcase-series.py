"""Five consecutive isolated 4.x business journeys; not a Stable release command."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    if os.environ.get('AIC_DISPOSABLE_ROAD_STACK') != '1':
        raise RuntimeError('explicit_isolated_stack_opt_in_required')
    if not os.environ.get('AIC_STACK_IMAGE') or not os.environ.get('AIC_STACK_FRONTEND_IMAGE'):
        raise RuntimeError('series_requires_explicit_candidate_images')
    root = Path(__file__).resolve().parents[1]
    output = Path(tempfile.mkdtemp(prefix='v45-showcase-series-', dir=root / 'output'))
    output.chmod(0o700)
    common = dict(os.environ, AIC_STACK_WITH_MAPS='1', AIC_STACK_SOURCE_OVERLAY='0',
        AIC_STACK_BROWSER='1', AIC_STACK_CASE_JOURNEY='1', AIC_STACK_EXTENDED_SHOWCASE='1',
        AIC_STACK_INFORMATION_GAP='1', AIC_STACK_PERIOD_BRIEF='1')
    for flag in ('AIC_STACK_WORKER_RECOVERY', 'AIC_STACK_REDIS_RECOVERY',
                 'AIC_STACK_ROAD_REFRESH', 'AIC_STACK_ROAD_EVALUATION', 'AIC_STACK_COVERAGE'):
        common.pop(flag, None)
    modes = [('normal', {}), ('worker_recovery', {'AIC_STACK_WORKER_RECOVERY': '1'}),
             ('redis_recovery', {'AIC_STACK_REDIS_RECOVERY': '1'}),
             ('road_refresh', {'AIC_STACK_ROAD_REFRESH': '1'}),
             ('frozen_road_replay', {'AIC_STACK_ROAD_EVALUATION': '1'})]
    report = {'passed': False, 'rounds': [], 'real_model_connected': False,
              'production_release': False, 'input_method': 'authenticated_api_synthetic_cases'}
    try:
        identities = None
        for index, (name, additions) in enumerate(modes, 1):
            print(f'Round {index}/5: {name}', flush=True)
            env = dict(common, AIC_STACK_BROWSER_ONLY='0' if index >= 4 else '1', **additions)
            process = subprocess.Popen([sys.executable, str(root / 'scripts/verify-road-stack.py')],
                cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            evidence = None
            with (output / f'{index}-{name}.log').open('w') as log:
                for line in process.stdout:
                    log.write(line)
                    if line.startswith('isolated_project='):
                        evidence = Path(line.split('evidence=', 1)[1].strip())
                    if line.startswith(('isolated_project=', 'Case saved', 'Core HTTP', 'Frozen road')):
                        print(line.rstrip(), flush=True)
            code = process.wait()
            assert evidence and evidence.parent == root / 'output', 'missing_owned_evidence'
            result = json.loads((evidence / 'report.json').read_text())
            report['rounds'].append({'name': name, 'exit_code': code, 'evidence': str(evidence),
                                     'stack': result})
            assert code == 0 and result['passed'] and result['owned_stack_removed'], f'round_failed:{name}'
            if name in ('worker_recovery', 'redis_recovery'):
                assert result[name]['actual_process_stop'] and result[name]['profile_count_after_journey'] == 1
            if name == 'road_refresh':
                assert result['real_publication_event_refresh']
            if name == 'frozen_road_replay':
                assert result['real_frozen_road_evaluation'] and result['road_evaluation_repeatability']
            browser = json.loads((evidence / 'browser.json').read_text())
            assert browser['real_https_login_secure_cookie'] and not browser['api_mocking']
            assert browser['case_journey']['completed'] and not browser['page_errors']
            for journey in ('coverage', 'query', 'information_gap', 'period_brief'):
                assert browser['extended_journeys'][journey]['completed'], f'missing_journey:{journey}'
            current = (result['image_id'], result['frontend_image_id'])
            assert all(current), 'series_requires_packaged_frontend_and_backend'
            if identities is None:
                identities = current
            assert current == identities, 'candidate_images_changed_during_series'
            print(f'Round {index}/5 passed', flush=True)
        report['passed'] = True
    finally:
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(f'Series evidence: {output}', flush=True)


if __name__ == '__main__':
    main()
