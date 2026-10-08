import copy
import importlib.util
from pathlib import Path

import pytest


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def observations(tmp_path):
    (tmp_path / 'synthetic.txt').write_text('Synthetic unit-test data: no human session occurred.')
    return [dict(participant_id=f'P{person}', task_id=str(task), human_observed='yes',
                 credential_ready='yes', onboarding_seconds='60', completed_without_help='yes',
                 ordinary_modals_after_trust='0', evidence='synthetic.txt')
            for person in range(5) for task in range(1, 4)]


def test_thresholds_and_missing_observations(tmp_path):
    evaluate = load('evaluate_g9_usability').evaluate
    rows = observations(tmp_path)
    assert evaluate(rows, tmp_path)['status'] == 'PASS'  # evaluator only, no human claim
    assert evaluate(rows[:-1], tmp_path)['status'] == 'BLOCKED'
    for field, value, status in [('ordinary_modals_after_trust', '1', 'FAIL'),
                                 ('human_observed', 'no', 'BLOCKED'), ('evidence', 'missing.txt', 'BLOCKED')]:
        changed = copy.deepcopy(rows)
        changed[0][field] = value
        assert evaluate(changed, tmp_path)['status'] == status
    for person in range(2):
        rows[person * 3]['completed_without_help'] = 'no'
    assert evaluate(rows, tmp_path)['status'] == 'FAIL'


def test_bad_numbers_duplicate_tasks_and_onboarding(tmp_path):
    evaluate = load('evaluate_g9_usability').evaluate
    for field, value in [('onboarding_seconds', 'nan'), ('ordinary_modals_after_trust', '-1'), ('task_id', '2')]:
        rows = observations(tmp_path)
        rows[0][field] = value
        with pytest.raises(ValueError):
            evaluate(rows, tmp_path)
    rows = observations(tmp_path)
    for row in rows:
        row['onboarding_seconds'] = '121'
    assert evaluate(rows, tmp_path)['status'] == 'FAIL'


def test_fixture_is_new_and_tests_really_fail_initially(tmp_path):
    import subprocess
    import sys
    setup = load('setup_g9_usability').create_fixture
    root = setup(tmp_path / 'participant')
    test = subprocess.run([sys.executable, '-m', 'unittest', '-v'], cwd=root, capture_output=True, text=True)
    assert test.returncode == 1 and 'FAILED' in test.stderr
    assert (root / 'review.txt').read_text() == 'status=original\n'
    with pytest.raises(FileExistsError):
        setup(root)


def test_evidence_cannot_escape_through_symlink(tmp_path):
    evaluate = load('evaluate_g9_usability').evaluate
    rows = observations(tmp_path)
    (tmp_path / 'alias.txt').symlink_to(tmp_path / 'synthetic.txt')
    rows[0]['evidence'] = 'alias.txt'
    with pytest.raises(ValueError, match='symlink'):
        evaluate(rows, tmp_path)
