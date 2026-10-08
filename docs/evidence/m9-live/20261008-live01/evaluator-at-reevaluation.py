"""Evidence checks for the synthetic, real-provider G9-06 fixture."""
import json


def evaluate_live(report):
    history = report.get('tool_history', [])
    read_paths = set()
    edit = False
    command = False
    for item in history:
        try:
            args = json.loads(item['arguments'])
            result = json.loads(item['result'])
        except (KeyError, TypeError, ValueError):
            continue
        if not isinstance(args, dict) or not isinstance(result, dict) or result.get('error'):
            continue
        if item['name'] == 'workspace_read':
            read_paths.add(args.get('path'))
        if item['name'] == 'workspace_edit' and args.get('path') == 'calc.py':
            edit = result.get('status') == 'written' and bool(result.get('receipt'))
        if item['name'] == 'workspace_run':
            argv = args.get('argv', [])
            command |= (len(argv) >= 3 and argv[1:3] == ['-m', 'unittest']
                        and result.get('exit_code') == 0 and not result.get('timed_out', True)
                        and 'OK' in result.get('output', ''))
    return {
        'negative_control': report.get('initial_test', {}).get('exit_code') == 1,
        'read_both_files': {'calc.py', 'test_calc.py'} <= read_paths,
        'edit_applied': edit,
        'sandboxed_tests_pass': command,
        'independent_tests_pass': report.get('final_test', {}).get('exit_code') == 0,
        'tests_unchanged': report.get('tests_unchanged') is True,
        'journal_verified': report.get('journal') == 'PASS',
        'provider_flow': bool(report.get('requests')) and not report.get('errors')
                         and report.get('turn') == 'completed',
    }
