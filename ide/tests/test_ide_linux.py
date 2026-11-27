"""Real namespace checks, never executed against the user's project or account."""
import asyncio
import json
from pathlib import Path

import pytest

from core.runtime.linux import CommandError, LinuxCommandRuntime, installation_status
from core.policy import PolicyEngine
from core.runtime import RuntimeRegistry
from core.runtime.base import ToolCall
from core.tool_execution import ToolExecutionService


def test_real_isolated_command_has_no_home_env_network_or_host_write(tmp_path, monkeypatch):
    if not installation_status()["installed"]:
        pytest.skip("Mandatory system launchers absent")
    monkeypatch.setenv("ISYCODE_TEST_SECRET", "must-not-enter")
    root = tmp_path / "project"
    root.mkdir()
    secret = tmp_path / "outside-secret"
    secret.write_text("private")
    (root / ".env").write_text("hidden")
    (root / "linked").symlink_to(secret)
    (root / "code.py").write_text("old\n")
    script = (
        "import os,json,socket;from pathlib import Path;"
        "s=socket.socket();s.settimeout(.2);"
        "r=s.connect_ex(('1.1.1.1',443));"
        "Path('code.py').write_text('new\\n');"
        "print(json.dumps({'network':r,'env':os.getenv('ISYCODE_TEST_SECRET'),"
        "'outside':Path(" + repr(str(secret)) + ").exists(),"
        "'dotenv':Path('.env').exists(),'linked':Path('linked').exists()}))"
    )
    async def run():
        runtime = LinuxCommandRuntime(root)
        request = runtime.prepare({"argv": ["python3", "-c", script]})
        return await runtime.run_request(request, authorize=lambda: True)
    report = asyncio.run(run())
    values = json.loads(report["stdout"])
    assert report["returncode"] == 0
    assert values["network"] != 0
    assert values["env"] is None
    assert values["outside"] is values["dotenv"] is values["linked"] is False
    assert report["changes"] == {"code.py": "new\n"}
    assert (root / "code.py").read_text() == "old\n"
    assert secret.read_text() == "private"


def test_permanent_command_grant_does_not_approve_resulting_file_changes(tmp_path):
    if not installation_status()["installed"]:
        pytest.skip("Mandatory system launchers absent")
    (tmp_path / "code.py").write_text("old")
    host = ToolExecutionService(tmp_path, PolicyEngine(), RuntimeRegistry(tmp_path))
    call = ToolCall("run_command", {"argv": ["python3", "-c", "from pathlib import Path;Path('code.py').write_text('new')"]}, "command")
    decisions = []
    async def reject_files(preview):
        decisions.append(preview.name)
        return "always" if preview.name == "run_command" else False
    result = asyncio.run(host.execute(call, mode="coder", approve=reject_files))
    assert result.error_code == "USER_REJECTED"
    assert decisions == ["run_command", "apply_changes"]
    assert (tmp_path / "code.py").read_text() == "old"
    decisions.clear()
    result = asyncio.run(host.execute(call, mode="coder", approve=reject_files))
    assert decisions == ["apply_changes"]
    assert (tmp_path / "code.py").read_text() == "old"


def test_namespace_failure_never_launches_requested_command(tmp_path, monkeypatch):
    runtime = LinuxCommandRuntime(tmp_path)
    if not installation_status()["installed"]:
        pytest.skip("Mandatory system launchers absent")
    request = runtime.prepare({"argv": ["true"]})
    from core.processes import ProcessOutput
    invoked = []
    async def denied(argv, **kwargs):
        invoked.append(argv)
        return ProcessOutput(1, b"", b"namespace unavailable")
    monkeypatch.setattr("core.runtime.linux.capture_process", denied)
    with pytest.raises(CommandError, match="LINUX_CAPABILITY_UNAVAILABLE"):
        asyncio.run(runtime.run_request(request, authorize=lambda: True))
    assert len(invoked) == 1
    assert "/broker.py" in invoked[0]
    assert not (tmp_path / ".isycode-ide" / "commands").exists()


def test_cancel_terminates_real_namespace_and_descendants(tmp_path, monkeypatch):
    if not installation_status()["installed"]:
        pytest.skip("Mandatory system launchers absent")
    async def run():
        runtime = LinuxCommandRuntime(tmp_path)
        request = runtime.prepare({"argv": ["python3", "-c", "import subprocess,time;subprocess.Popen(['python3','-c','import time;time.sleep(60)']);time.sleep(60)"]})
        await runtime.check_capabilities(request)
        processes = []
        original = asyncio.create_subprocess_exec
        async def capture(*args, **kwargs):
            process = await original(*args, **kwargs)
            processes.append(process)
            return process
        monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
        task = asyncio.create_task(runtime.run_request(request, authorize=lambda: True))
        def descendants(pid):
            try:
                children = [int(value) for value in Path(f"/proc/{pid}/task/{pid}/children").read_text().split()]
            except OSError:
                return []
            return children + [sub for child in children for sub in descendants(child)]
        seen = []
        for _ in range(300):
            await asyncio.sleep(0.01)
            if processes:
                seen = descendants(processes[-1].pid)
                if len(seen) >= 4:
                    break
        assert processes and len(seen) >= 4
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert processes[-1].returncode is not None
        for _ in range(100):
            alive = []
            for pid in seen:
                try:
                    state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
                    if state != "Z":
                        alive.append(pid)
                except OSError:
                    pass
            if not alive:
                break
            await asyncio.sleep(0.01)
        assert not alive
    asyncio.run(run())
