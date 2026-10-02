import json

import pytest

from isycode.user_defaults import UserDefaultsStore


def test_unlimited_default_survives_an_unrelated_settings_update(tmp_path):
    store = UserDefaultsStore(tmp_path)
    assert store.load()['answer_tokens'] is None
    store.update(new_workspace_mode='classic')
    assert store.load()['answer_tokens'] is None
    assert store.load()['new_workspace_mode'] == 'classic'


@pytest.mark.parametrize('invalid', [True, 1.5, '8192', [], {}, -1, 999])
def test_invalid_answer_limits_still_fail_closed(tmp_path, invalid):
    store = UserDefaultsStore(tmp_path)
    data = store.load()
    data['answer_tokens'] = invalid
    store.path.write_text(json.dumps(data))
    store.path.chmod(0o600)
    with pytest.raises(ValueError, match='answer length'):
        store.load()
