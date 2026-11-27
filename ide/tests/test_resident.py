import json

from core.resident import ResidentReader, ResidentRecorder, SelfScanner


def seed_project(root):
    (root / "core" / "runtime").mkdir(parents=True)
    (root / "core" / "runtime" / "base.py").write_text("# runtime\n", encoding="utf-8")
    (root / "core" / "policy.py").write_text("# policy\n", encoding="utf-8")
    (root / "contracts").mkdir()
    (root / "contracts" / "vm.iesy").write_text("Identity: vm\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_runtime.py").write_text("# test\n", encoding="utf-8")


def test_self_map_loads_as_jsonl_and_surfaces_protected_components(tmp_path):
    seed_project(tmp_path)
    summary = SelfScanner(tmp_path).scan()
    assert summary["status"] == "ok"
    reader = ResidentReader(tmp_path)
    assert reader.status()["components"] > 0
    guidance = reader.query("modify core/runtime/base.py")
    assert guidance["status"] == "verified"
    assert any(item.get("path") == "core/runtime/base.py" for item in guidance["protected"])


def test_malformed_jsonl_is_not_treated_as_knowledge(tmp_path):
    scanner = SelfScanner(tmp_path)
    seed_project(tmp_path)
    scanner.scan()
    with (scanner.recorder.root / "self_map.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{broken\n")
    result = ResidentReader(tmp_path).verify()
    assert result["status"] == "fail"


def test_unknown_intent_remains_unknown(tmp_path):
    seed_project(tmp_path)
    SelfScanner(tmp_path).scan()
    result = ResidentReader(tmp_path).query("modify imaginary_component_xyz")
    assert result["status"] == "unknown"
    assert result["relevant"] == []
    assert result["tests"] == []


def test_reader_has_no_mutation_or_execution_api(tmp_path):
    reader = ResidentReader(tmp_path)
    assert not hasattr(reader, "record")
    assert not hasattr(reader, "write")
    assert not hasattr(reader, "execute")
    assert not hasattr(reader, "shell")


def test_recorder_writes_change_and_session_context(tmp_path):
    recorder = ResidentRecorder(tmp_path)
    recorder.session_start("session-test", "modify hello")
    recorder.change("hello.py", "modified", "session-test")
    recorder.verification("hello.py", "verified", ["tests/test_resident.py"])
    reader = ResidentReader(tmp_path)
    assert len(reader._records("changes.jsonl")) == 2
    session = reader._records("sessions/session-test.jsonl")
    assert session[0]["event"] == "started"


def test_provider_is_injectable_without_network(tmp_path):
    seed_project(tmp_path)
    SelfScanner(tmp_path).scan()
    calls = []

    def fake_provider(guidance):
        calls.append(guidance["intent"])
        return {"summary": "deterministic fake resident guidance"}

    result = ResidentReader(tmp_path).query("modify core/agent/run.py", provider=fake_provider)
    assert calls == ["modify core/agent/run.py"]
    assert result["model_guidance"]["summary"].startswith("deterministic")


def test_query_categories_are_structured(tmp_path):
    seed_project(tmp_path)
    SelfScanner(tmp_path).scan()
    result = ResidentReader(tmp_path).query("runtime", category="architecture")
    assert result["category"] == "architecture"
    assert "relevant" in result and "protected" in result
    unknown = ResidentReader(tmp_path).query("runtime", category="not-a-category")
    assert unknown["status"] == "unknown"


def test_jsonl_records_are_independent_objects(tmp_path):
    seed_project(tmp_path)
    SelfScanner(tmp_path).scan()
    lines = (tmp_path / ".isycode-ide" / "resident" / "self_map.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines
    assert all(isinstance(json.loads(line), dict) for line in lines)


def test_scan_reports_file_directory_and_protected_changes(tmp_path):
    seed_project(tmp_path)
    scanner = SelfScanner(tmp_path)
    scanner.scan()
    (tmp_path / "new.py").write_text("new = True\n", encoding="utf-8")
    (tmp_path / "new_dir").mkdir()
    (tmp_path / "core" / "runtime" / "base.py").write_text("changed\n", encoding="utf-8")
    (tmp_path / "core" / "policy.py").unlink()
    result = scanner.scan()
    assert "new.py" in result["files_added"]
    assert "new_dir" in result["directories_added"]
    assert "core/runtime/base.py" in result["files_modified"]
    assert "core/policy.py" in result["files_deleted"]
    assert "core/policy.py" in result["protected_touches"]


def test_scan_is_deterministic_when_nothing_changes(tmp_path):
    seed_project(tmp_path)
    scanner = SelfScanner(tmp_path)
    scanner.scan()
    second = scanner.scan()
    assert second["files_added"] == []
    assert second["files_modified"] == []
    assert second["files_deleted"] == []
    assert second["directories_added"] == []
    assert second["directories_deleted"] == []
