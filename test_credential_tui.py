"""TUI key entry: masked, cleared at once, never displayed, saved only via the owner."""
import ast
from pathlib import Path

SOURCE = Path(__file__).parent / "isycode" / "tui.py"


def _methods():
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == "TUIApp")
    return {node.name: node for node in app.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _segment(name):
    return ast.get_source_segment(SOURCE.read_text(encoding="utf-8"), _methods()[name])


def test_key_input_is_masked():
    assert 'Input(placeholder="Paste API key…", password=True, id="provider-key-input")' in \
        SOURCE.read_text(encoding="utf-8")


def test_the_pasted_key_is_cleared_before_anything_else():
    save = _segment("_save_provider_key")
    assert save.index('secret, key_input.value = key_input.value, ""') < save.index("self._close_menu()")


def test_the_secret_never_reaches_messages_activity_or_state():
    source = SOURCE.read_text(encoding="utf-8")
    for name, node in _methods().items():
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            target = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
            if target not in {"_append", "_set_activity", "notify", "log", "print"}:
                continue
            names = {item.id for item in ast.walk(call) if isinstance(item, ast.Name)}
            assert "secret" not in names, name
        for assign in ast.walk(node):
            if isinstance(assign, ast.Assign):
                value_names = {item.id for item in ast.walk(assign.value) if isinstance(item, ast.Name)}
                if "secret" in value_names:
                    stores = [ast.get_source_segment(source, target) or ""
                              for target in assign.targets]
                    assert not any(text.startswith("self.") for text in stores), name


def test_keys_are_saved_and_removed_only_through_the_owner_after_confirmation():
    save = _segment("_save_key_flow")
    assert save.index("_ensure_credential_grant") < save.index("TailscaleConfirmScreen")
    assert save.index("TailscaleConfirmScreen") < save.index("owner.add, request")
    revoke = _segment("_revoke_key_flow")
    assert revoke.index("TailscaleConfirmScreen") < revoke.index("owner.revoke, request")
    for name in ("_save_key_flow", "_revoke_key_flow", "_save_provider_key", "_open_credentials_menu"):
        segment = _segment(name)
        assert "vault.add" not in segment and "CredentialVault().add" not in segment, name
        assert "CredentialVault().revoke" not in segment, name
