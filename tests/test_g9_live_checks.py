import copy
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location('g9_live_checks', Path(__file__).parents[1] / 'scripts/g9_live_checks.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fixture():
    def item(name, args, result):
        return dict(name=name, arguments=json.dumps(args), result=json.dumps(result))
    return dict(initial_test={'exit_code': 1}, final_test={'exit_code': 0}, tests_unchanged=True,
                journal='PASS', turn='completed', requests=[{'usage': {'prompt_tokens': 10}}], errors=[],
                tool_history=[item('workspace_read', {'path': p}, {'text': 'fixture'}) for p in ['calc.py', 'test_calc.py']] + [
                    item('workspace_edit', {'path': 'calc.py'}, {'status': 'written', 'receipt': 'real-id'}),
                    item('workspace_run', {'argv': ['python3', '-m', 'unittest', '-v']}, {'exit_code': 0, 'timed_out': False, 'output': 'Ran 1 test\nOK'})])


def test_complete_flow_passes_but_false_success_does_not():
    assert all(mod.evaluate_live(fixture()).values())
    for key, value in [('initial_test', {'exit_code': 0}), ('final_test', {'exit_code': 1}),
                       ('tests_unchanged', False), ('journal', 'FAIL'), ('requests', []),
                       ('errors', ['RATE_LIMIT'])]:
        data = copy.deepcopy(fixture())
        data[key] = value
        assert not all(mod.evaluate_live(data).values()), key


def test_missing_receipt_or_timed_out_command_never_passes():
    for index, result in [(2, {'status': 'written'}), (3, {'exit_code': 0, 'timed_out': True, 'output': 'OK'})]:
        data = fixture()
        data['tool_history'][index]['result'] = json.dumps(result)
        assert not all(mod.evaluate_live(data).values())


def test_fixture_scope_rejects_host_code_and_unrelated_tools():
    assert mod.safe_calc_fixture('def add(a, b):\n    return a + b\n')
    assert not mod.safe_calc_fixture('import os\ndef add(a, b):\n    return a + b\n')
    assert not mod.safe_calc_fixture('def add(a, b):\n    return a - b\n')
    def call(name, args):
        return {'function': {'name': name, 'arguments': json.dumps(args)}}
    assert mod.permitted_call(call('workspace_edit', {'path': 'calc.py'}))
    assert not mod.permitted_call(call('workspace_edit', {'path': 'test_calc.py'}))
    assert not mod.permitted_call(call('workspace_run', {'argv': ['curl', 'https://example.com']}))
    assert not mod.permitted_call(call('workspace_read', {'path': '../private.txt'}))
