"""A native keyring backend failure must fail closed, never crash the caller."""
import sys
import types

import pytest

from isycode.credentials import CredentialVault, CredentialVaultError


class NativePanic(BaseException):
    """Stand-in for pyo3_runtime.PanicException, which derives from BaseException."""


def _fake_keyring(monkeypatch, get_keyring):
    keyring = types.ModuleType("keyring")
    keyring.get_keyring = get_keyring
    backends = types.ModuleType("keyring.backends")
    fail = types.ModuleType("keyring.backends.fail")
    fail.Keyring = type("Keyring", (), {})
    monkeypatch.setitem(sys.modules, "keyring", keyring)
    monkeypatch.setitem(sys.modules, "keyring.backends", backends)
    monkeypatch.setitem(sys.modules, "keyring.backends.fail", fail)


def _panic():
    raise NativePanic("Python API call failed")


def test_native_keyring_panic_becomes_a_closed_vault_error(tmp_path, monkeypatch):
    _fake_keyring(monkeypatch, _panic)
    with pytest.raises(CredentialVaultError):
        CredentialVault(tmp_path / "credentials.sqlite3")


def test_provider_state_degrades_instead_of_crashing(tmp_path, monkeypatch):
    from isycode.providers import provider_credential_state

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    for name in ("OPENAI_API_KEY", "ISYCODE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    _fake_keyring(monkeypatch, _panic)
    assert provider_credential_state("openai") in {"unavailable", "missing"}


def test_keyboard_interrupt_still_propagates(tmp_path, monkeypatch):
    def interrupt():
        raise KeyboardInterrupt

    _fake_keyring(monkeypatch, interrupt)
    with pytest.raises(KeyboardInterrupt):
        CredentialVault(tmp_path / "credentials.sqlite3")
