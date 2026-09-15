"""Run one module/role safely; upstream requests are opt-in and separately recorded."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

TEST_ROOT = Path(__file__).resolve().parents[1]
PROJECT = TEST_ROOT.parent


def main(module, fixed_role=None, *, candidate=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', choices=['gys', 'zyc', 'all'], default=fixed_role or 'all')
    parser.add_argument('--list', action='store_true', help='List selected cases without running')
    parser.add_argument('--phase', choices=['offline', 'live', 'all'], default='live' if module == 'test_ai' else 'offline')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--claude-settings', type=Path)
    parser.add_argument('--repeat', type=int, choices=range(1,4), default=1)
    parser.add_argument('--group', choices=['all','controlled','production'], default='all')
    parser.add_argument('--case-ids', nargs='+')
    parser.add_argument('--effort', choices=['low','medium','high'], default='low')
    parser.add_argument('--output', type=Path, help='New evidence directory for live execution only')
    parser.add_argument('--allow-paid', action='store_true')
    parser.add_argument('--workers', type=int, choices=[1, 2], default=2)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--max-requests', type=int, default=20)
    args = parser.parse_args()
    if fixed_role and args.role != fixed_role:
        parser.error('This entry point belongs to role ' + fixed_role)
    if module != 'test_ai' and args.phase != 'offline':
        parser.error('Only test_ai supports live/all; manual online tests have a separate runner')
    if args.config and args.claude_settings:
        parser.error('Choose only one API configuration source')
    if not args.list and args.phase != 'offline' and (not (args.config or args.claude_settings) or not args.allow_paid):
        parser.error('Real API calls require --claude-settings (or --config) and --allow-paid; use --phase offline for mocks')
    folder = TEST_ROOT / module
    if module == 'manual_tests':
        from TEST.manual_tests.case_index import resolved_cases
        offline_cases = resolved_cases()
    else:
        offline_cases = json.loads((folder / 'cases.json').read_text(encoding='utf-8'))['offline_cases']
    selected = [c for c in offline_cases if args.role == 'all' or c['role'] == args.role]
    if not selected:
        parser.error('No cases selected')
    chosen = TEST_ROOT / '_shared/fix_candidates' if candidate else PROJECT
    sys.path.insert(0, str(PROJECT))
    sys.path.insert(0, str(chosen))
    if args.list:
        if args.phase != 'live':
            for c in selected:
                print(c['id'] + '  ' + c['test'])
            print('Offline count:', len(selected))
        if args.phase != 'offline':
            from TEST.test_ai.live_api.run import main as live_main
            return live_main(['--list', '--role', args.role, '--group', args.group, *(['--case-ids',*args.case_ids] if args.case_ids else [])])
        return 0
    passed = True
    role_dir = args.role
    if args.phase != 'live':
        from TEST._shared.evidence import EvidenceResult
        import anomaly_factory.review_server as loaded
        assert Path(loaded.__file__).resolve().is_relative_to(chosen.resolve()), loaded.__file__
        output = folder / 'reports' / role_dir / ('candidate' if candidate else 'baseline')
        output.mkdir(parents=True, exist_ok=True)
        temp = output / 'tmp'
        temp.mkdir(exist_ok=True)
        os.environ['ANOMALY_TEST_TMPDIR'] = str(temp)
        tempfile.tempdir = str(temp)
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(c['test']) for c in selected)
        begin = time.monotonic()
        result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(suite)
        import PIL
        report = {'module': module, 'role': args.role, 'variant': 'candidate' if candidate else 'baseline',
                  'date_utc': datetime.now(timezone.utc).isoformat(), 'python': sys.version.split()[0],
                  'pillow': PIL.__version__, 'tests_run': result.testsRun, 'failures': len(result.failures),
                  'errors': len(result.errors), 'skipped': len(result.skipped), 'records': result.records,
                  'seconds': round(time.monotonic()-begin, 3), 'upstream_calls': 0,
                  'loaded_source': str(loaded.__file__),
                  'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in (chosen / 'anomaly_factory').glob('*.py')},
                  'provenance': 'AI-assisted; roles are responsibilities, not claimed human authorship'}
        (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Report:', output / 'results.json')
        passed = result.wasSuccessful()
        if temp.exists() and not any(temp.iterdir()):
            temp.rmdir()  # Empty task-owned directory only.
        tempfile.tempdir = None
        os.environ.pop('ANOMALY_TEST_TMPDIR', None)
    if args.phase != 'offline':
        from TEST.test_ai.live_api.run import main as live_main
        live_output = args.output or folder / 'reports' / role_dir / ('live_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        config_args = ['--claude-settings', str(args.claude_settings.resolve())] if args.claude_settings else ['--config', str(args.config.resolve())]
        code = live_main([*config_args, '--allow-paid', '--role', args.role, '--repeat', str(args.repeat),
                          '--group', args.group, '--effort', args.effort,
                          *(['--case-ids',*args.case_ids] if args.case_ids else []),
                          '--workers', str(args.workers), '--timeout', str(args.timeout),
                          '--max-requests', str(args.max_requests), '--output', str(live_output)])
        passed = passed and code == 0
    elif module == 'test_ai':
        print('Offline only. Real API cases were NOT run.')
    return 0 if passed else 1
