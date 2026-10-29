from isycode.notification_sounds import PATTERNS
from isycode.user_defaults import UserDefaultsStore


def test_semantic_rhythms_are_distinct_bounded_and_preference_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert len({PATTERNS[k] for k in ("done", "approval", "question", "error")}) == 4
    assert all(len(p) <= 3 and max(p) < 1 for p in PATTERNS.values())
    store = UserDefaultsStore()
    assert store.load()["notification_sounds"] is True
    store.update(notification_sounds=False)
    assert UserDefaultsStore().load()["notification_sounds"] is False
