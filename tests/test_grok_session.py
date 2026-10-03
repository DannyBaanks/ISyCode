"""Grok sign-in is a transport choice. The refresh token never leaves auth.json."""
import json
from datetime import datetime, timedelta, timezone

from isycode.grok_session import (
    SESSION_BASE, access_token, public_login_line, set_xai_auth_mode, status, xai_auth_mode,
)
from isycode.providers import Provider


def _auth(path, *, key="test-token-not-real", expires="2099-01-01T00:00:00+00:00",
          refresh="refresh-token-must-stay"):
    path.write_text(json.dumps({"https://auth.x.ai::client": {
        "key": key, "refresh_token": refresh, "expires_at": expires,
        "oidc_issuer": "https://auth.x.ai", "auth_mode": "oidc",
    }}), encoding="utf-8")


def test_status_names_a_live_sign_in_without_the_token(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    _auth(auth)
    monkeypatch.setattr("isycode.grok_session.auth_file", lambda: auth)
    assert status() == "signed-in"
    assert "test-token-not-real" not in status()
    assert "refresh-token" not in status()
    assert access_token() == "test-token-not-real"


def test_expired_and_missing_sign_ins_do_not_return_a_token(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    expired = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    _auth(auth, expires=expired)
    monkeypatch.setattr("isycode.grok_session.auth_file", lambda: auth)
    assert status() == "expired"
    assert access_token() == ""
    monkeypatch.setattr("isycode.grok_session.auth_file", lambda: tmp_path / "absent.json")
    assert status() == "missing"
    assert access_token() == ""


def test_session_mode_points_chat_at_the_grok_proxy(tmp_path, monkeypatch):
    monkeypatch.setenv("ISYCODE_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("ISYCODE_BASE_URL", raising=False)
    monkeypatch.delenv("ISYMOTRON_BASE_URL", raising=False)
    auth = tmp_path / "auth.json"
    _auth(auth)
    monkeypatch.setattr("isycode.grok_session.auth_file", lambda: auth)
    assert xai_auth_mode() == "api_key"
    set_xai_auth_mode("session")
    assert xai_auth_mode() == "session"
    provider = Provider(name="xai", model="grok-4.7")
    assert provider.base_url == SESSION_BASE
    assert provider.api_key == "test-token-not-real"
    assert provider.configured()
    set_xai_auth_mode("api_key")
    keyed = Provider(name="xai", model="grok-4", api_key="xai-test-key")
    assert keyed.base_url == "https://api.x.ai/v1"
    assert keyed.api_key == "xai-test-key"


def test_login_lines_keep_the_code_and_drop_a_bare_token():
    assert public_login_line("  Open https://auth.x.ai/device and enter ABCD-EFGH  ") == (
        "Open https://auth.x.ai/device and enter ABCD-EFGH")
    assert public_login_line("x" * 90) is None
    assert public_login_line("") is None
