from isycode import action_coverage
from isycode.actions import ACTION_BY_ID, ACTION_CATALOG, ActionSpec
from isycode.action_runtime import (
    EXPLICIT_DENY_ACTIONS, OWNER_ACTIONS, OWNER_ACTION_VARIANTS,
    OWNER_REQUIRED_SYSTEMBILITIES, ProductActionGate,
)
from isycode.security import ActionRequest, AuthorityDecision
from isycode.workspace_authority import WorkspaceAuthority
import isycode.security as security_module


def test_owner_coverage_report_exposes_unowned_actions_and_effect_callsites():
    report = action_coverage.owner_coverage_report()

    assert report["secure_closed"] is True
    assert "mobile.host.start" not in report["unowned_effectful_actions"]
    assert "oauth.authorize" in report["unowned_effectful_actions"]
    assert "credentials.add" not in report["unowned_effectful_actions"]
    callsites = {item["callsite"]: item for item in report["callsites"]}
    assert callsites["MobileHostOwner.authorize_and_launch"]["status"] == "COVERED"
    assert callsites["MobileHostOwner.shutdown"]["status"] == "BLOCKED_BY_DESIGN"
    assert callsites["BridgeClient.agents"]["status"] == "UNWIRED"
    assert callsites["BridgeClient._run"]["status"] == "UNWIRED"
    assert callsites["file_picker.choose_context_file"]["status"] == "BLOCKED_BY_DESIGN"
    assert callsites["file_picker.choose_workspace_file"]["status"] == "BLOCKED_BY_DESIGN"
    assert callsites["file_picker.choose_workspace_directory"]["status"] == "BLOCKED_BY_DESIGN"
    assert callsites["CredentialOwner.add"]["status"] == "COVERED"
    assert set(report["unowned_effectful_actions"]) <= EXPLICIT_DENY_ACTIONS


def test_secure_tui_direct_api_audit_finds_app_and_constructed_modal_bypasses():
    source = '''
class Screen: pass
class ModalScreen:
    def __class_getitem__(cls, item): return cls
class ChatSessionsScreen(ModalScreen[str]):
    def on_button_pressed(self):
        self.session_store.delete("session-1")
class TUIApp:
    def action_start_host(self):
        self._mobile_host.start()
    def action_sessions(self):
        self.push_screen(ChatSessionsScreen())
'''

    issues = action_coverage.secure_tui_direct_api_bypasses(source)

    assert any(item["callsite"].endswith("self._mobile_host.start")
               for item in issues)
    assert any(item["callsite"].endswith("self.session_store.delete")
               for item in issues)


def test_secure_tui_direct_api_audit_tracks_sensitive_object_aliases():
    source = '''
class TUIApp:
    def action_start_host(self):
        host = self._mobile_host
        host.start()
'''

    issues = action_coverage.secure_tui_direct_api_bypasses(source)

    assert any(item["callsite"].endswith("host.start") for item in issues)


def test_secure_tui_direct_api_audit_follows_nested_constructed_screens():
    source = '''
class Screen: pass
class ModalScreen: pass
class InnerScreen(ModalScreen):
    def on_mount(self):
        self.bridge_client.heartbeat()
class OuterScreen(ModalScreen):
    def open_inner(self):
        self.app.push_screen(InnerScreen())
class TUIApp:
    def action_open(self):
        self.push_screen(OuterScreen())
'''

    issues = action_coverage.secure_tui_direct_api_bypasses(source)

    assert any(item["callsite"].endswith("self.bridge_client.heartbeat")
               for item in issues)


def test_secure_tui_direct_api_audit_fails_closed_for_unparseable_source():
    issues = action_coverage.secure_tui_direct_api_bypasses("class TUIApp(:")

    assert issues
    assert "SyntaxError" in issues[0]["reason"]


def test_secure_tui_direct_api_audit_finds_no_current_direct_bypasses():
    assert action_coverage.secure_tui_direct_api_bypasses() == []
    assert action_coverage.owner_coverage_report()["secure_tui_closed"] is True


def test_owner_coverage_report_detects_unknown_owner_action(monkeypatch):
    monkeypatch.setattr(action_coverage, "OWNER_ACTIONS", {"test_owner": frozenset({"not.real"})})

    report = action_coverage.owner_coverage_report()

    assert report["owner_action_mismatches"] == ["test_owner:not.real"]
    assert {item["action"] for item in report["actions"]} == set(ACTION_BY_ID)


def test_owner_coverage_report_detects_ambiguous_conflicting_owner():
    report = action_coverage.owner_coverage_report()

    assert report["ambiguous_actions"] == []
    broker_start = next(item for item in report["actions"] if item["action"] == "broker.start")
    assert broker_start["classification"] == "OWNER_VARIANTS"
    assert {item["owner"] for item in broker_start["variants"]} == {
        "broker_provision", "broker_management",
    }


def test_declared_effect_callsites_reference_catalog_actions():
    assert {item[0] for item in action_coverage.KNOWN_EFFECT_CALLSITES} <= set(ACTION_BY_ID)


def test_tailscale_contract_actions_have_one_owner_and_named_pending_callsite():
    report = action_coverage.owner_coverage_report()
    expected = {
        "tailscale.inspect": "tailscale_read",
        "tailscale.install.prepare": "tailscale_package_install",
        "tailscale.install.stage": "tailscale_package_install",
        "tailscale.install": "tailscale_package_install",
        "tailscale.login": "tailscale_login",
        "tailscale.serve.enable": "tailscale_serve",
        "tailscale.serve.disable": "tailscale_serve",
    }
    rows = {row["action"]: row for row in report["actions"]}
    for action, owner in expected.items():
        assert rows[action]["classification"] == "OWNER_VALID"
        assert rows[action]["owners"] == [owner]
        callsites = [item for item in report["callsites"] if item["action"] == action]
        assert len(callsites) == 1
        assert callsites[0]["owner"] == owner
        assert callsites[0]["callsite"]
        assert callsites[0]["status"] == "COVERED"
    assert report["authority_frontier_pass"] is True
    assert report["unclassified_actions"] == []


def test_every_catalog_action_has_an_explicit_authority_classification():
    report = action_coverage.owner_coverage_report()

    assert report["authority_frontier_pass"] is True
    assert report["unclassified_actions"] == []
    registered = {action for actions in OWNER_ACTIONS.values() for action in actions}
    assert set(EXPLICIT_DENY_ACTIONS).isdisjoint(registered)
    assert set(ACTION_BY_ID) - registered == set(EXPLICIT_DENY_ACTIONS) | {"role.select"}
    assert sum(row["classification"] == "EXPLICIT_DENY" for row in report["actions"]) == 24


def test_unclassified_effectful_catalog_addition_fails_the_frontier(monkeypatch):
    new_action = ActionSpec("test.new_effect", "Test", "Unclassified test effect", "process", True)
    catalog = (*ACTION_CATALOG, new_action)
    monkeypatch.setattr(action_coverage, "ACTION_CATALOG", catalog)
    monkeypatch.setattr(action_coverage, "ACTION_BY_ID", {item.id: item for item in catalog})

    report = action_coverage.owner_coverage_report()

    assert report["authority_frontier_pass"] is False
    assert report["unclassified_actions"] == ["test.new_effect"]


def test_explicitly_denied_effect_cannot_be_registered_to_an_owner(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    gate = ProductActionGate(root, authority, owner_id="provider_network")
    request = ActionRequest(
        "workspace.files.read_sensitive", root, str(root / ".env"), {},
        execution_owner="provider_network")
    authority_result = AuthorityDecision(True, "grant:test", "fixture", request.digest)

    decision = gate.sentinel.evaluate(request, authority_result)

    check = next(item for item in decision.checks if item.name == "ExecutionOwnerBinding")
    assert check.passed is False
    assert check.reason == "action is explicitly denied in Secure"

    # Writes have their own owner; any other owner is still refused.
    write = ActionRequest("workspace.files.write", root, str(root / "new.txt"), {},
                          execution_owner="provider_network")
    write_decision = gate.sentinel.evaluate(
        write, AuthorityDecision(True, "grant:test", "fixture", write.digest))
    assert not write_decision.allowed


def test_broker_start_owner_variants_are_disjoint_and_cross_owner_denies(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    variants = {item.owner_id: item for item in OWNER_ACTION_VARIANTS}
    assert set(variants) == {"broker_provision", "broker_management"}

    for owner, variant in variants.items():
        params = dict(variant.required_parameters)
        params.update({"executable": "/usr/bin/docker"})
        request = ActionRequest("broker.start", root, "/project", params,
                                execution_owner=owner)
        accepted_gate = ProductActionGate(root, authority, owner_id=owner)
        accepted = next(item for item in accepted_gate.sentinel.evaluate(
            request, AuthorityDecision(True, "grant:test", "fixture", request.digest)).checks
                        if item.name == "ExecutionOwnerBinding")
        assert accepted.passed is True

        other = "broker_management" if owner == "broker_provision" else "broker_provision"
        crossed_gate = ProductActionGate(root, authority, owner_id=other)
        crossed = next(item for item in crossed_gate.sentinel.evaluate(
            request, AuthorityDecision(True, "grant:test", "fixture", request.digest)).checks
                       if item.name == "ExecutionOwnerBinding")
        assert crossed.passed is False

        malformed_parameters = dict(params)
        if owner == "broker_provision":
            malformed_parameters["managed_existing"] = True
        else:
            malformed_parameters["managed_existing"] = False
        malformed = ActionRequest("broker.start", root, "/project", malformed_parameters,
                                  execution_owner=owner)
        malformed_check = next(item for item in accepted_gate.sentinel.evaluate(
            malformed, AuthorityDecision(True, "grant:test", "fixture", malformed.digest)).checks
                               if item.name == "ExecutionOwnerBinding")
        assert malformed_check.passed is False

    assert OWNER_REQUIRED_SYSTEMBILITIES["broker_provision"] != \
        OWNER_REQUIRED_SYSTEMBILITIES["broker_management"]


def test_every_declared_owner_boundary_is_installed_in_product_sentinel(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    gate = ProductActionGate(root, authority, owner_id="workspace_read")
    installed = {item.name for item in gate.sentinel._systembilities}

    assert set(OWNER_REQUIRED_SYSTEMBILITIES) == set(OWNER_ACTIONS)
    assert set().union(*OWNER_REQUIRED_SYSTEMBILITIES.values()) <= installed


def test_each_explicit_deny_is_rejected_by_the_runtime_owner_binding(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    gate = ProductActionGate(root, authority, owner_id="provider_network")
    for action_id in sorted(EXPLICIT_DENY_ACTIONS):
        request = ActionRequest(action_id, root, "/target", {},
                                execution_owner="provider_network")
        decision = gate.sentinel.evaluate(
            request, AuthorityDecision(True, "grant:test", "fixture", request.digest))
        binding = next(item for item in decision.checks if item.name == "ExecutionOwnerBinding")
        assert binding.passed is False, action_id
        assert decision.status == "DENY", action_id


def test_new_known_effect_without_owner_is_denied_before_execution(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    spec = ActionSpec("test.new_effect", "Test", "New effect", "process", True)
    monkeypatch.setitem(security_module.ACTION_BY_ID, spec.id, spec)
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "authority")
    gate = ProductActionGate(root, authority, owner_id="provider_network")
    request = ActionRequest(spec.id, root, "/target", {},
                            execution_owner="provider_network")
    decision = gate.sentinel.evaluate(
        request, AuthorityDecision(True, "grant:test", "fixture", request.digest))

    known = next(item for item in decision.checks if item.name == "KnownAction")
    owner = next(item for item in decision.checks if item.name == "ExecutionOwnerBinding")
    assert known.passed is True
    assert owner.passed is False
    assert decision.status == "DENY"


def test_checked_in_snapshot_matches_live_catalog_and_owners():
    import json
    from pathlib import Path

    snapshot_path = Path(__file__).parent / "docs" / "security" / "m15-authority-coverage.json"
    checked_in = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert checked_in == action_coverage.authority_coverage_snapshot()


def test_bypass_scanner_converges_when_one_name_aliases_several_receivers():
    import time

    from isycode.action_coverage import secure_tui_direct_api_bypasses

    methods = "".join(
        f"    def method_{index}(self):\n"
        "        owner = self._chat_session_owner\n"
        "        owner = self._mobile_host_owner\n"
        "        owner.record('user', 'x')\n"
        for index in range(300))
    source = "class TUIApp:\n" + methods + "    def leak(self):\n        owner.save()\n"
    started = time.monotonic()
    issues = secure_tui_direct_api_bypasses(source)
    assert time.monotonic() - started < 10
    assert any(item["callsite"].endswith("owner.save") for item in issues)
    assert not any(item["callsite"].endswith("owner.record") for item in issues)
