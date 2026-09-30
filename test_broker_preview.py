import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from isycode.approvals import ActionApprovalStore
from isycode.broker import (
    BrokerManagementOwner, BrokerPreviewOwner, BrokerProvisionOwner, BrokerRegistry,
    load_reviewed_recipe, provision_requests,
)
from isycode.workspace_authority import WorkspaceAuthority


@pytest.mark.integration
def test_recipe_is_fixed_to_configured_isyco_checkout(monkeypatch):
    checkout = Path.home() / "Development" / "ISyCo"
    monkeypatch.setenv("ISYCO_ROOT", str(checkout))

    recipe = load_reviewed_recipe()

    assert recipe.source_root == (checkout / "tools" / "semantic_gateway").resolve()
    assert len(recipe.digest) == 64
    assert {name for name, _ in recipe.files} == {
        "Dockerfile", "requirements.txt", "semantic_gateway/app.py",
        "semantic_gateway/manager.py",
    }


@pytest.mark.integration
def test_preview_requires_read_authority_and_never_executes_docker(tmp_path, monkeypatch):
    checkout = Path.home() / "Development" / "ISyCo"
    monkeypatch.setenv("ISYCO_ROOT", str(checkout))
    workspace = tmp_path / "workspace"
    project = workspace / "chosen"
    project.mkdir(parents=True)
    authority = WorkspaceAuthority(workspace, state_directory=tmp_path / "state")
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[project])
    authority.set_grant("broker.preview", enabled=True)
    owner = BrokerPreviewOwner(workspace, authority, ActionApprovalStore())

    outcome = owner.preview(project, None)

    assert outcome.decision == "ALLOW"
    plan = json.loads(outcome.text)
    assert plan["operation"] == "preview-only"
    assert plan["mount"] == {"source": str(project), "target": "/workspace", "read_only": True}
    assert plan["network"] == {"mode": "internal-only", "host_exposure": "127.0.0.1 only"}
    assert plan["executed"] is False


def test_preview_denies_selected_path_outside_isyroot(tmp_path, monkeypatch):
    checkout = Path.home() / "Development" / "ISyCo"
    monkeypatch.setenv("ISYCO_ROOT", str(checkout))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    authority = WorkspaceAuthority(workspace, state_directory=tmp_path / "state")
    authority.set_grant("broker.preview", enabled=True)
    owner = BrokerPreviewOwner(workspace, authority, ActionApprovalStore())

    outcome = owner.preview(outside, None)

    assert outcome.decision == "DENY"
    assert "Broker preview denied" in outcome.text


@pytest.mark.integration
def test_provision_owner_requires_grants_and_uses_bound_approvals(
        tmp_path, monkeypatch):
    import isycode.broker as broker_module

    checkout = Path.home() / "Development" / "ISyCo"
    monkeypatch.setenv("ISYCO_ROOT", str(checkout))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    project = workspace / "chosen"
    project.mkdir(parents=True)
    fake_docker = tmp_path / "docker"
    fake_docker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_docker.chmod(0o700)
    monkeypatch.setattr(broker_module.shutil, "which", lambda name: str(fake_docker))
    recipe = load_reviewed_recipe()
    build, start = provision_requests(workspace, project, recipe, str(fake_docker))
    authority = WorkspaceAuthority(workspace, state_directory=tmp_path / "state")
    authority.set_grant("workspace.files.read", enabled=True, path_prefixes=[project])
    authority.set_grant("broker.build", enabled=True, executables=[fake_docker])
    authority.set_grant("broker.start", enabled=True, executables=[fake_docker])
    approvals = ActionApprovalStore()
    build_approval = approvals.issue(build)
    start_approval = approvals.issue(start)

    calls = []

    def fake_run(args, **kwargs):
        calls.append(tuple(args[1:]))
        if args[1:] == ["inspect", start.parameters["container"]]:
            return SimpleNamespace(returncode=1, stdout="")
        if args[1:3] == ["network", "inspect"]:
            return SimpleNamespace(returncode=0, stdout="true\n")
        if args[1] == "port":
            return SimpleNamespace(returncode=0, stdout="127.0.0.1:41001\n")
        return SimpleNamespace(returncode=0, stdout="container-id\n")

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return b'{"ok":true}'

    class Opener:
        def open(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(broker_module.subprocess, "run", fake_run)
    monkeypatch.setattr(broker_module, "build_opener", lambda *_args: Opener())
    monkeypatch.setattr(broker_module, "_container_ip", lambda *_args: "172.20.0.2")
    monkeypatch.setattr(broker_module, "_start_proxy", lambda *_args: (41001, 4242))
    monkeypatch.setattr(broker_module, "_wait_for_health", lambda *_args: None)

    outcome = BrokerProvisionOwner(workspace, authority, approvals).provision(
        project, build_approval, start_approval)

    assert outcome.decision == "ALLOW"
    assert outcome.receipt is not None and outcome.receipt.verify(start, outcome.text)
    assert "healthy" in outcome.text
    assert any(args[:2] == ("build", "--tag") for args in calls)
    assert any("--internal" in args for args in calls)
    run_args = next(args for args in calls if args and args[0] == "run")
    assert "--read-only" in run_args
    assert "--cap-drop" in run_args and "ALL" in run_args
    assert not any(argument in {"--publish", "-p"} for argument in run_args)
    assert not any("--privileged" in args for args in calls)
    registry = BrokerRegistry()
    registered = registry.get(workspace, project)
    assert registered["status"] == "healthy"
    assert registered["host_port"] == 41001
    assert registry.path.is_relative_to(tmp_path / "state")


def test_broker_registry_rejects_tampered_docker_identity(tmp_path):
    workspace = tmp_path / "workspace"
    project = workspace / "chosen"
    project.mkdir(parents=True)
    registry = BrokerRegistry(tmp_path / "state")
    digest = "a" * 64
    registry.register(
        workspace, project, recipe_digest=digest,
        image=f"isycode-semantic-broker:{digest[:16]}",
        container=f"isycode-semantic-{registry.root_id(project)}",
        network=f"isycode-internal-{registry.root_id(project)}", host_port=41001)
    state = registry._load()
    state["brokers"][registry.root_id(project)]["network"] = "another-project-network"
    registry._write(state)

    try:
        registry.get(workspace, project)
    except ValueError as exc:
        assert "identity" in str(exc)
    else:
        raise AssertionError("tampered network identity was accepted")


def test_broker_registry_keeps_cleanup_identity_if_project_was_deleted(tmp_path):
    workspace = tmp_path / "workspace"
    project = workspace / "chosen"
    project.mkdir(parents=True)
    registry = BrokerRegistry(tmp_path / "state")
    digest = "d" * 64
    root_id = registry.root_id(project)
    registry.register(workspace, project, recipe_digest=digest,
                      image=f"isycode-semantic-broker:{digest[:16]}",
                      container=f"isycode-semantic-{root_id}",
                      network=f"isycode-internal-{root_id}", host_port=41001)
    project.rmdir()

    assert registry.get(workspace, project)["project_root"] == str(project)
    assert len(registry.list_for_workspace(workspace)) == 1


def test_broker_management_requires_request_bound_log_approval(
        tmp_path, monkeypatch):
    import isycode.broker as broker_module

    workspace = tmp_path / "workspace"
    project = workspace / "chosen"
    project.mkdir(parents=True)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    docker = tmp_path / "docker"
    docker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    docker.chmod(0o700)
    registry = BrokerRegistry()
    digest = "b" * 64
    root_id = registry.root_id(project)
    registry.register(workspace, project, recipe_digest=digest,
                      image=f"isycode-semantic-broker:{digest[:16]}",
                      container=f"isycode-semantic-{root_id}",
                      network=f"isycode-internal-{root_id}", host_port=41001)
    authority = WorkspaceAuthority(workspace, state_directory=tmp_path / "authority")
    authority.set_grant("broker.logs", enabled=True)
    approvals = ActionApprovalStore()
    owner = BrokerManagementOwner(workspace, authority, approvals, str(docker))
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args[1:])
        if args[1:3] == ["network", "inspect"]:
            return SimpleNamespace(returncode=0, stdout=(
                f'{{"isycode.managed":"true","isycode.root":"{root_id}"}}|true'))
        if args[1] == "inspect":
            return SimpleNamespace(returncode=0, stdout=(
                f'{{"isycode.managed":"true","isycode.root":"{root_id}"}}|'
                f'{registry.get(workspace, project)["image"]}|true'))
        return SimpleNamespace(returncode=0, stdout="token=sk_12345678901234567890\nready\n")

    monkeypatch.setattr(broker_module.subprocess, "run", fake_run)
    denied = owner.perform(project, "logs")
    assert denied.decision == "DENY"
    assert calls == []

    request, _ = owner.request_for(project, "logs")
    approval = approvals.issue(request)
    allowed = owner.perform(project, "logs", approval)
    assert allowed.decision == "ALLOW"
    assert allowed.receipt is not None and allowed.receipt.verify(request, allowed.text)
    assert "[REDACTED]" in allowed.text
    assert "sk_12345678901234567890" not in allowed.text


def test_broker_management_restarts_registered_container_and_verifies_health(
        tmp_path, monkeypatch):
    import isycode.broker as broker_module

    workspace = tmp_path / "workspace"
    project = workspace / "chosen"
    project.mkdir(parents=True)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    docker = tmp_path / "docker"
    docker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    docker.chmod(0o700)
    registry = BrokerRegistry()
    digest = "c" * 64
    root_id = registry.root_id(project)
    container = f"isycode-semantic-{root_id}"
    image = f"isycode-semantic-broker:{digest[:16]}"
    registry.register(workspace, project, recipe_digest=digest, image=image,
                      container=container, network=f"isycode-internal-{root_id}",
                      host_port=41001)
    authority = WorkspaceAuthority(workspace, state_directory=tmp_path / "authority")
    authority.set_grant("broker.start", enabled=True, executables=[docker])
    approvals = ActionApprovalStore()
    owner = BrokerManagementOwner(workspace, authority, approvals, str(docker))
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args[1:])
        if args[1:3] == ["network", "inspect"]:
            return SimpleNamespace(returncode=0, stdout=(
                f'{{"isycode.managed":"true","isycode.root":"{root_id}"}}|true'))
        if args[1] == "inspect":
            running = "true" if any(call and call[0] == "start" for call in calls) else "false"
            return SimpleNamespace(returncode=0, stdout=(
                f'{{"isycode.managed":"true","isycode.root":"{root_id}"}}|{image}|{running}'))
        if args[1] == "port":
            return SimpleNamespace(returncode=0, stdout="127.0.0.1:41001\n")
        return SimpleNamespace(returncode=0, stdout="started\n")

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return b'{"ok":true}'

    class Opener:
        def open(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(broker_module.subprocess, "run", fake_run)
    monkeypatch.setattr(broker_module, "build_opener", lambda *_args: Opener())
    monkeypatch.setattr(broker_module, "_wait_for_health", lambda *_args: None)
    request, _ = owner.request_for(project, "start")
    outcome = owner.perform(project, "start", approvals.issue(request))

    assert outcome.decision == "ALLOW"
    assert outcome.receipt is not None and outcome.receipt.verify(request, outcome.text)
    assert any(call[:2] == ["start", container] for call in calls)
    assert registry.get(workspace, project)["status"] == "healthy"
