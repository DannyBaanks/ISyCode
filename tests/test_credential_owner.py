"""Saving and revoking API keys is owned, approved, and never journals the secret."""
from pathlib import Path

import pytest

from isycode.action_runtime import ProductActionGate
from isycode.approvals import ActionApprovalStore
from isycode.credential_owner import CredentialOwner, credential_services
from isycode.security import ActionRequest
from isycode.workspace_authority import WorkspaceAuthority

SECRET = "sk-test-" + "Z" * 40


class MemoryVault:
    """Stand-in for the OS keyring vault; keeps values only in memory."""

    def __init__(self):
        self.records, self.values, self.counter = [], {}, 0

    def add(self, name, service, purpose, secret):
        self.counter += 1
        key_id = f"cred_{self.counter:016x}"
        self.records.append({"id": key_id, "name": name, "service": service,
                             "purpose": purpose, "revoked": False})
        self.values[key_id] = secret
        return key_id

    def list_metadata(self):
        return [dict(item) for item in self.records]

    def revoke(self, key_id):
        for item in self.records:
            if item["id"] == key_id and not item["revoked"]:
                item["revoked"] = True
                self.values.pop(key_id, None)
                return True
        return False


@pytest.fixture
def keys(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "workspace"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    approvals = ActionApprovalStore()
    vault = MemoryVault()
    owner = CredentialOwner(root, authority, approvals, vault=vault)
    return owner, authority, approvals, vault, root.resolve(), tmp_path


def grant(authority, service="openai"):
    for action in ("credentials.add", "credentials.revoke"):
        authority.set_grant(action, enabled=True, targets=[service])


def test_services_are_the_provider_presets_plus_the_gateway():
    assert {"openai", "isyco-gateway"} <= credential_services()


def test_saving_needs_the_service_grant_and_a_fresh_approval(keys):
    owner, authority, approvals, vault, _, _ = keys
    request = owner.add_request("openai", "OpenAI key", "ISyCode chat")
    assert owner.add(request, SECRET, approvals.issue(request)).decision == "DENY"
    grant(authority)
    assert owner.add(request, SECRET, None).decision == "DENY"
    assert vault.records == []
    approval = approvals.issue(request)
    outcome = owner.add(request, SECRET, approval)
    assert outcome.decision == "ALLOW" and outcome.receipt is not None
    assert vault.values == {outcome.reason: SECRET}
    assert owner.add(request, SECRET, approval).decision == "DENY"  # approval is one-use


def test_a_grant_for_one_service_does_not_cover_another(keys):
    owner, authority, approvals, vault, _, _ = keys
    grant(authority, "openai")
    request = owner.add_request("groq", "Groq key", "ISyCode chat")
    assert owner.add(request, SECRET, approvals.issue(request)).decision == "DENY"
    assert vault.records == []


def test_the_secret_never_reaches_any_state_file(keys):
    owner, authority, approvals, _, _, tmp_path = keys
    grant(authority)
    request = owner.add_request("openai", "OpenAI key", "ISyCode chat")
    assert owner.add(request, SECRET, approvals.issue(request)).decision == "ALLOW"
    stored = b"".join(path.read_bytes() for path in (tmp_path / "state").rglob("*")
                      if path.is_file())
    assert SECRET.encode() not in stored
    assert SECRET not in repr(request)


def test_revoke_removes_the_key_with_its_own_approval(keys):
    owner, authority, approvals, vault, _, _ = keys
    grant(authority)
    add = owner.add_request("openai", "OpenAI key", "ISyCode chat")
    key_id = owner.add(add, SECRET, approvals.issue(add)).reason
    request = owner.revoke_request(key_id)
    assert owner.revoke(request, None).decision == "DENY"
    outcome = owner.revoke(request, approvals.issue(request))
    assert outcome.decision == "ALLOW" and vault.values == {}
    with pytest.raises(ValueError):
        owner.revoke_request(key_id)  # already revoked


@pytest.mark.parametrize("secret", ["", "   ", "two\nlines", "x" * 20_000])
def test_malformed_secrets_are_refused_before_authorization(keys, secret):
    owner, authority, approvals, vault, _, _ = keys
    grant(authority)
    request = owner.add_request("openai", "OpenAI key", "ISyCode chat")
    assert owner.add(request, secret, approvals.issue(request)).decision == "DENY"
    assert vault.records == []


@pytest.mark.parametrize("action, target, parameters", [
    ("credentials.add", "evil", {"service": "evil", "name": "k", "purpose": "p"}),
    ("credentials.add", "openai", {"service": "openai", "name": "k", "purpose": "p",
                                   "secret": SECRET}),
    ("credentials.add", "groq", {"service": "openai", "name": "k", "purpose": "p"}),
    ("credentials.revoke", "openai", {"service": "openai", "key_id": "../../etc"}),
])
def test_sentinel_rejects_forged_credential_requests(keys, action, target, parameters):
    _, authority, approvals, _, root, _ = keys
    for service in ("openai", "groq", "evil"):
        grant(authority, service)
    request = ActionRequest(action, root, target, parameters, execution_owner="credentials")
    gate = ProductActionGate(root, authority, owner_id="credentials")
    assert not gate.authorize(request, approvals=approvals,
                              approval=approvals.issue(request))[1].allowed


# ── credentials.use: one owned, journaled decision per saved-key read ──

class ReadableVault(MemoryVault):
    def latest_secret_for_service(self, service):
        active = [item for item in self.records if item["service"] == service and not item["revoked"]]
        return self.values.get(active[-1]["id"]) if active else None


@pytest.fixture
def use(tmp_path: Path, monkeypatch):
    from isycode.credential_owner import CredentialUseOwner

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "workspace"
    root.mkdir()
    authority = WorkspaceAuthority(root, state_directory=tmp_path / "state" / "authority")
    vault = ReadableVault()
    vault.add("OpenAI key", "openai", "ISyCode chat", SECRET)
    return CredentialUseOwner(root, authority, vault=vault), authority, root.resolve(), tmp_path


def test_saved_key_is_not_read_without_the_use_grant(use):
    owner, _, _, _ = use
    outcome, secret = owner.secret_for("openai", "provider.request")
    assert outcome.decision == "DENY" and secret is None


def test_each_read_is_its_own_journaled_decision_and_never_stores_the_value(use):
    from isycode.action_audit import ActionAuditJournal

    owner, authority, root, tmp_path = use
    authority.set_grant("credentials.use", enabled=True, targets=["openai"])
    for _ in range(3):
        outcome, secret = owner.secret_for("openai", "provider.request")
        assert outcome.decision == "ALLOW" and secret == SECRET and outcome.receipt
    report = ActionAuditJournal(root).verify()
    assert report.status == "PASS" and report.decisions == 3 and report.receipts == 3
    stored = b"".join(path.read_bytes() for path in (tmp_path / "state").rglob("*") if path.is_file())
    assert SECRET.encode() not in stored


def test_use_grant_is_per_service_and_consumer_is_bounded(use):
    owner, authority, _, _ = use
    authority.set_grant("credentials.use", enabled=True, targets=["groq"])
    assert owner.secret_for("openai", "provider.request")[1] is None
    authority.set_grant("credentials.use", enabled=True, targets=["openai"])
    assert owner.secret_for("openai", "shell")[1] is None


def test_without_a_registered_reader_no_saved_key_is_read(monkeypatch):
    import isycode.credentials as credentials
    from isycode.providers import load_provider_key

    def vault_must_not_open(*args, **kwargs):
        raise AssertionError("the vault was opened without a registered reader")

    credentials.set_saved_secret_reader(None)
    monkeypatch.setattr(credentials, "CredentialVault", vault_must_not_open)
    monkeypatch.setattr("isycode.providers.load_api_key", lambda name: "")
    assert credentials.read_saved_secret("openai", "provider.request") is None
    assert load_provider_key("openai") == ""


def test_registered_reader_failures_read_as_no_key():
    import isycode.credentials as credentials

    def broken(service, consumer):
        raise RuntimeError("keyring exploded")

    credentials.set_saved_secret_reader(broken)
    try:
        assert credentials.read_saved_secret("openai", "provider.request") is None
    finally:
        credentials.set_saved_secret_reader(None)


def test_only_the_use_owner_reads_saved_secret_values():
    import ast

    package = Path(__file__).resolve().parents[1] / "src" / "isycode"
    allowed = {"credentials.py", "credential_owner.py"}
    for module in package.glob("*.py"):
        if module.name in allowed:
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"latest_secret_for_service", "get_secret"}:
                raise AssertionError(f"{module.name} reads a saved secret directly")
