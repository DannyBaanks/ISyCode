"""Hermetic tests for ``isycode setup`` (interactive and non-interactive)."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from isycode import launcher
from isycode.config import credential_state, load_api_key
from isycode.mcp_local import load_config as load_mcp_config
from isycode.providers import model_slot, selected_model_name, selected_provider_name
from isycode.setup_wizard import (
    EXIT_CANCELLED,
    EXIT_FAILED,
    EXIT_OK,
    EXIT_USAGE,
    SetupIO,
    main as setup_main,
)
from isycode.user_defaults import UserDefaultsStore
from isycode.workspace_authority import WorkspaceAuthority


def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Isolate XDG config/state/home and key store inside tmp_path."""
    state_dir = tmp_path / "state"
    config_dir = tmp_path / "config"
    workspace_dir = tmp_path / "project"
    state_dir.mkdir(mode=0o700)
    config_dir.mkdir(mode=0o700)
    workspace_dir.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(state_dir))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))
    monkeypatch.setenv("ISYCODE_STATE_DIR", str(state_dir / "isycode"))
    monkeypatch.setenv("ISYMOTRON_KEY_STORE", str(config_dir / "isymotron" / "keys.env"))
    for var in (
        "ISYCODE_PROVIDER",
        "ISYCODE_MODEL",
        "ISYMOTRON_PROVIDER",
        "ISYMOTRON_MODEL",
        "ISYMOTRON_API_KEY",
        "NVIDIA_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "OPENAI_API_KEY",
        "GATEWAY_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    return workspace_dir


def test_status_json_is_offline_and_structured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = _isolated_env(monkeypatch, tmp_path)
    out = io.StringIO()
    err = io.StringIO()
    rc = setup_main(
        ["--status", "--json"],
        io=SetupIO(out=out, err=err, is_tty=False, use_color=False),
        cwd=workspace,
    )
    assert rc == EXIT_OK
    assert err.getvalue() == ""
    data = json.loads(out.getvalue())
    assert data["network_tested"] is False
    assert data["workspace"]["root"] == str(workspace.resolve())
    assert "provider" in data
    assert "integrations" in data
    assert "paths" in data


def test_noninteractive_full_setup_persists_all_stores(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _isolated_env(monkeypatch, tmp_path)
    monkeypatch.setenv("MY_NV_SECRET", "nvapi-test-token-12345")
    out = io.StringIO()
    err = io.StringIO()
    rc = setup_main(
        [
            "--non-interactive",
            "--locale", "en",
            "--provider", "nvidia",
            "--model", "nvidia/nemotron-3-ultra-550b-a55b",
            "--small-model", "groq:openai/gpt-oss-120b",
            "--gus-model", "openai:gpt-6-luna",
            "--api-key-env", "MY_NV_SECRET",
            "--key-storage", "file",
            "--workspace", str(workspace),
            "--init-workspace",
            "--mode", "flow",
            "--default-mode", "classic",
            "--new-workspace", "recurring",
            "--mcp-preset", "playwright",
            "--agent-steps", "25",
            "--answer-tokens", "8192",
            "--chat-token-budget", "100000",
            "--json",
        ],
        io=SetupIO(out=out, err=err, is_tty=False, use_color=False),
        cwd=workspace,
    )
    assert rc == EXIT_OK, err.getvalue()
    payload = json.loads(out.getvalue())
    # Secret value must never be echoed in output.
    assert "nvapi-test-token-12345" not in out.getvalue()
    assert payload["changes"]["provider"] == "nvidia"
    assert payload["changes"]["workspace_mode"] == "flow"
    assert payload["changes"]["mcp_added"] == ["playwright"]

    assert (workspace / ".isyroot").is_file()
    assert selected_provider_name() == "nvidia"
    assert selected_model_name() == "nvidia/nemotron-3-ultra-550b-a55b"
    assert model_slot("small") == {"provider": "groq", "model": "openai/gpt-oss-120b"}
    assert model_slot("gus") == {"provider": "openai", "model": "gpt-6-luna"}
    assert credential_state("nvidia") == "stored"
    assert load_api_key("nvidia") == "nvapi-test-token-12345"
    assert WorkspaceAuthority(workspace).mode() == "flow"

    defaults = UserDefaultsStore().load()
    assert defaults["locale"] == "en"
    assert defaults["new_workspace_mode"] == "classic"
    assert defaults["new_workspace"] == "recurring"
    assert defaults["agent_steps"] == 25
    assert defaults["answer_tokens"] == 8192
    assert defaults["chat_token_budget"] == 100000

    mcp_servers = load_mcp_config()
    assert "playwright" in mcp_servers


def test_noninteractive_rejects_broad_workspace_init(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_env(monkeypatch, tmp_path)
    out = io.StringIO()
    err = io.StringIO()
    rc = setup_main(
        ["--non-interactive", "--workspace", str(Path.home()), "--init-workspace"],
        io=SetupIO(out=out, err=err, is_tty=False, use_color=False),
        cwd=tmp_path,
    )
    assert rc == EXIT_FAILED
    assert "Rechazado" in err.getvalue()


def test_noninteractive_rejects_unknown_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _isolated_env(monkeypatch, tmp_path)
    out = io.StringIO()
    err = io.StringIO()
    rc = setup_main(
        ["--non-interactive", "--provider", "does-not-exist"],
        io=SetupIO(out=out, err=err, is_tty=False, use_color=False),
        cwd=workspace,
    )
    assert rc == EXIT_USAGE


def test_no_tty_prints_guidance_without_mutating(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _isolated_env(monkeypatch, tmp_path)
    out = io.StringIO()
    err = io.StringIO()
    rc = setup_main(
        [],
        io=SetupIO(out=out, err=err, is_tty=False, use_color=False),
        cwd=workspace,
    )
    assert rc == EXIT_OK
    assert "Modo no interactivo" in out.getvalue()
    assert not (workspace / ".isyroot").exists()


def test_interactive_quick_setup_and_isymcp_hub_section(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _isolated_env(monkeypatch, tmp_path)
    fake_hub = tmp_path / "isymcp-hub"
    fake_hub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_hub.chmod(0o755)
    monkeypatch.setattr("isycode.setup_wizard._detect_isymcp_hub", lambda: str(fake_hub))
    monkeypatch.setattr("isycode.setup_wizard.keyring_available", lambda: False)

    # First-time interactive quick setup:
    # 1) mode=1 (quick)
    # 2) locale=1 (es)
    # 3) provider=1 (nvidia)
    # 4) model="" (accept default)
    # 5) secret="nvapi-interactive-secret" (stored to keys.env since keyring=False)
    # 6) create .isyroot=s
    # 7) workspace mode=3 (flow)
    # 8) new workspace mode=2 (classic)
    # 9) new workspace recurrence=2 (recurring)
    answers = iter(["1", "1", "1", "", "s", "3", "2", "2"])
    out = io.StringIO()
    err = io.StringIO()
    rc = setup_main(
        [],
        io=SetupIO(
            out=out,
            err=err,
            input_fn=lambda _p: next(answers),
            secret_fn=lambda _p: "nvapi-interactive-secret",
            is_tty=True,
            use_color=False,
        ),
        cwd=workspace,
    )
    assert rc == EXIT_OK, err.getvalue()
    assert "ISyCode Setup Complete!" in out.getvalue()
    assert "nvapi-interactive-secret" not in out.getvalue()
    assert (workspace / ".isyroot").is_file()
    assert selected_provider_name() == "nvidia"
    assert load_api_key("nvidia") == "nvapi-interactive-secret"
    assert WorkspaceAuthority(workspace).mode() == "flow"

    # Now run only the `mcp` section and accept ISyMCP Hub + decline playwright/context7.
    mcp_answers = iter(["s", "n", "n"])
    out2 = io.StringIO()
    rc2 = setup_main(
        ["mcp"],
        io=SetupIO(
            out=out2,
            err=err,
            input_fn=lambda _p: next(mcp_answers),
            is_tty=True,
            use_color=False,
        ),
        cwd=workspace,
    )
    assert rc2 == EXIT_OK
    servers = load_mcp_config()
    assert "isymcp-hub" in servers
    assert servers["isymcp-hub"].argv == (str(fake_hub),)


def test_interactive_ctrl_c_cancels_cleanly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _isolated_env(monkeypatch, tmp_path)
    out = io.StringIO()
    err = io.StringIO()

    def _abort(_prompt: str) -> str:
        raise KeyboardInterrupt()

    rc = setup_main(
        [],
        io=SetupIO(out=out, err=err, input_fn=_abort, is_tty=True, use_color=False),
        cwd=workspace,
    )
    assert rc == EXIT_CANCELLED
    assert "Setup cancelado" in out.getvalue()


def test_launcher_dispatches_setup_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _isolated_env(monkeypatch, tmp_path)
    monkeypatch.chdir(workspace)
    rc = launcher.main(["setup", "--status", "--json"])
    assert rc == EXIT_OK
    data = json.loads(capsys.readouterr().out)
    assert data["network_tested"] is False
    assert data["workspace"]["root"] == str(workspace.resolve())
