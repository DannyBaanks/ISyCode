"""Machine-readable local inspection commands adopted from the CLI audits."""
from __future__ import annotations

import io
import json
from pathlib import Path

from isycode.chat_sessions import ChatSessionStore
from isycode.inspection_cli import main
from isycode.providers import save_model_slot, save_provider_selection
from isycode.usage import UsageLedger
from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_setup import WorkspaceSetupStore


def setup_workspace(tmp_path: Path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("ISYCODE_MODEL", raising=False)
    monkeypatch.setenv("ISYCODE_PROVIDER", "openai")
    authority = WorkspaceAuthority(root)
    authority.set_mode("classic")
    store = ChatSessionStore(WorkspaceSetupStore().sessions_root(root))
    session = store.create("Investigate parser")
    store.append(session.session_id, "user", "api_key=sk-secret-fixture parser regression")
    session = store.load(session.session_id)
    ledger = UsageLedger()
    ledger.record({"prompt_tokens": 11, "completion_tokens": 4})
    session.state = {"usage": ledger.to_state()}
    store.save(session)
    return root.resolve(), authority, store, session.session_id


def invoke(root: Path, args: list[str]):
    out, err = io.StringIO(), io.StringIO()
    code = main(args, cwd=root, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_sessions_list_last_show_and_stats_are_json_and_sanitized(tmp_path, monkeypatch):
    root, _authority, _store, session_id = setup_workspace(tmp_path, monkeypatch)

    code, text, _ = invoke(root, ["sessions", "list", "--json"])
    listed = json.loads(text)
    assert code == 0 and listed["sessions"][0]["id"] == session_id

    code, text, _ = invoke(root, ["sessions", "last", "--json"])
    assert code == 0 and json.loads(text)["session"]["id"] == session_id

    code, text, _ = invoke(root, ["sessions", "show", session_id, "--json"])
    shown = json.loads(text)
    assert code == 0 and shown["session"]["id"] == session_id
    assert "sk-secret-fixture" not in text and "[redacted]" in text

    code, text, _ = invoke(root, ["stats", "--json"])
    stats = json.loads(text)
    assert code == 0
    assert stats["sessions"] == 1
    assert stats["usage"] == {"requests": 1, "input_tokens": 11,
                              "output_tokens": 4, "unknown_requests": 0}


def test_models_dirs_and_completion_are_local_metadata_only(tmp_path, monkeypatch):
    root, _authority, _store, _session_id = setup_workspace(tmp_path, monkeypatch)
    save_provider_selection("openai", "gpt-fixture")
    save_model_slot("small", "openai", "gpt-small-fixture")

    code, text, _ = invoke(root, ["models", "--json"])
    models = json.loads(text)
    assert code == 0
    assert models["active"] == {"provider": "openai", "model": "gpt-fixture"}
    assert models["slots"]["small"] == {"provider": "openai", "model": "gpt-small-fixture"}

    code, text, _ = invoke(root, ["dirs", "--json"])
    dirs = json.loads(text)
    assert code == 0 and dirs["workspace"] == str(root)
    assert [item["precedence"] for item in dirs["configuration"]] == [1, 2, 3]
    assert "OPENAI_API_KEY" not in text and "secret" not in text.casefold()

    code, text, _ = invoke(root, ["completion", "bash"])
    assert code == 0 and "isycode" in text and "sessions" in text


def test_session_rename_and_delete_reuse_owners_and_receipts(tmp_path, monkeypatch):
    root, authority, store, session_id = setup_workspace(tmp_path, monkeypatch)

    code, text, _ = invoke(root, ["sessions", "rename", session_id, "New title", "--json"])
    renamed = json.loads(text)
    assert code == 0 and renamed["decision"] == "ALLOW" and renamed["receipt"]
    assert store.load(session_id).title == "New title"

    code, text, _ = invoke(root, ["sessions", "delete", session_id, "--json"])
    assert code == 3 and json.loads(text)["status"] == "confirmation_required"
    assert store.load(session_id).title == "New title"

    authority.set_grant("session.delete", enabled=True, targets=[session_id])
    code, text, _ = invoke(root, ["sessions", "delete", session_id, "--yes", "--json"])
    deleted = json.loads(text)
    assert code == 0 and deleted["decision"] == "ALLOW" and deleted["receipt"]
    assert store.list_sessions() == []
