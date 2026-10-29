from isycode.session_owner import ChatSessionOwner
from isycode.workspace_authority import WorkspaceAuthority


def test_agent_title_window_preserves_identity_and_manual_title(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "project"; root.mkdir()
    auth = WorkspaceAuthority(root); auth.set_mode("classic")
    owner = ChatSessionOwner(root, auth, tmp_path / "sessions")
    result, sid = owner.record(None, "user", "Hola :p")
    assert result.decision == "ALLOW"
    for index in range(1, 6):
        if index > 1:
            assert owner.record(sid, "user", f"Task {index}")[0].decision == "ALLOW"
        assert owner.manage("auto_title", sid, f"Real task {index}")[0].decision == "ALLOW"
        assert owner.resume(sid)[1].session_id == sid
    owner.record(sid, "user", "Sixth message")
    assert owner.manage("auto_title", sid, "Too late")[0].decision == "DENY"
    _, second = owner.record(None, "user", "Hola")
    assert owner.manage("rename", second, "My own name")[0].decision == "ALLOW"
    assert owner.manage("auto_title", second, "Overwrite")[0].decision == "DENY"
    assert owner.resume(second)[1].title == "My own name"
