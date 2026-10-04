import json
from isycode.capability_observations import observed, record
from isycode.image_attachments import accepts_images

def test_model_results_survive_reload_and_do_not_cross_providers(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert observed("one", "model", "images") is None
    assert record("one", "model", "images", True)
    assert accepts_images("one", "model") is True
    assert accepts_images("two", "model") is None
    assert record("one", "model", "images", False)
    assert observed("one", "model", "images") is False
    path = tmp_path / "isycode/model-capabilities.jsonl"
    assert len(path.read_text().splitlines()) == 2
    assert path.stat().st_mode & 0o077 == 0
    assert not record("one", "auto", "images", True)

def test_partial_observation_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    record("one", "model", "images", True)
    path = tmp_path / "isycode/model-capabilities.jsonl"
    with path.open("a") as stream:
        stream.write('{"provider":')
    assert observed("one", "model", "images") is True
    record("one", "model", "images", False)
    assert observed("one", "model", "images") is False


def test_wrong_shape_observations_do_not_crash_selector(tmp_path, monkeypatch):
    from isycode.capability_observations import supported_models
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    record("one", "model", "steer", True)
    path = tmp_path / "isycode/model-capabilities.jsonl"
    with path.open("a") as stream:
        stream.write('[]\n{"provider":[],"model":{},"feature":"steer","supported":true}\n')
    assert observed("one", "model", "steer") is True
    assert supported_models("steer") == (("one", "model"),)
