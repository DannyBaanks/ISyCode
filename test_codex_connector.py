"""Local fake app-server tests. No installed Codex or credential store is used."""
import asyncio
import json
from pathlib import Path
import sys

import pytest

from isycode.codex_connector import CodexConnector, CodexConnectorError


FAKE = r'''
import json, os, pathlib, signal, sys, time
SCENARIO = __SCENARIO__
home = pathlib.Path(os.environ["CODEX_HOME"])
(home / "child.json").write_text(json.dumps({
    "argv": sys.argv[1:], "cwd": os.getcwd(), "keys": sorted(os.environ),
    "home": os.environ.get("HOME"), "proxy": os.environ.get("HTTPS_PROXY"),
    "ca": os.environ.get("SSL_CERT_FILE"), "path": os.environ.get("PATH")}))
if SCENARIO == "ignore_terminate":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
def emit(value):
    sys.stdout.write(json.dumps(value) + "\n")
    sys.stdout.flush()
def note(method, params):
    emit({"method": method, "params": params})
def answer(req, value):
    emit({"id": req["id"], "result": value})
account = {"type": "apiKey"} if SCENARIO == "api_account" else {
    "type": "chatgpt", "planType": "plus", "email": "private@example.invalid", "accessToken": "SECRET"}
for line in sys.stdin:
    req = json.loads(line)
    with (home / "requests.jsonl").open("a") as log:
        log.write(json.dumps(req) + "\n")
    method = req.get("method")
    if method == "initialize":
        if SCENARIO in ("timeout", "ignore_terminate"):
            time.sleep(30)
        elif SCENARIO == "malformed":
            sys.stdout.write('{"token":"SECRET",broken}\n'); sys.stdout.flush()
        elif SCENARIO == "oversized":
            sys.stdout.write('x' * 1_000_002 + '\n'); sys.stdout.flush()
        elif SCENARIO == "nonfinite":
            sys.stdout.write('{"id":1,"result":{"a":NaN}}\n'); sys.stdout.flush()
        elif SCENARIO == "wrong_home":
            answer(req, {"codexHome": "/wrong", "userAgent": "fake"})
        elif SCENARIO == "rpc_error":
            emit({"id": req["id"], "error": {"code": -1, "message": "SECRET"}})
        else:
            if SCENARIO == "stderr":
                sys.stderr.write("SECRET" * 50000); sys.stderr.flush()
            answer(req, {"codexHome": str(home), "userAgent": "fake", "platformOs": "linux", "platformFamily": "unix"})
    elif method == "account/read":
        answer(req, {"account": None if SCENARIO == "signed_out" else account, "requiresOpenaiAuth": True})
    elif method == "model/list":
        if req["params"].get("cursor"):
            answer(req, {"data": [{"model": "m2"}], "nextCursor": None})
        else:
            answer(req, {"data": [{"model": "m1"}, {"model": "hidden", "hidden": True}], "nextCursor": "second"})
    elif method == "account/login/start":
        kind = req["params"]["type"]
        value = {"type": kind, "loginId": "login-1"}
        value.update({"authUrl": "https://auth.openai.com/authorize?state=CHALLENGE"} if kind == "chatgpt" else {
            "verificationUrl": "https://chatgpt.com/device", "userCode": "ABCD-EFGH"})
        if SCENARIO.startswith("bad_url:"):
            value["authUrl"] = SCENARIO.split(":", 1)[1]
        if SCENARIO == "wrong_login_type":
            value["type"] = "apiKey"
        if SCENARIO == "early_login":
            note("account/login/completed", {"loginId": "login-1", "success": True})
        answer(req, value)
        if SCENARIO not in ("pending_login", "early_login") and not SCENARIO.startswith("bad_url:"):
            note("account/login/completed", {"loginId": "login-1", "success": SCENARIO != "login_denied", "error": "SECRET" if SCENARIO == "login_denied" else None})
    elif method == "account/login/cancel":
        answer(req, {"status": "canceled"})
    elif method == "account/logout":
        answer(req, {})
    elif method == "thread/start":
        thread = {"id": "thread-1", "environments": []}
        if SCENARIO == "missing_environments":
            thread.pop("environments")
        elif SCENARIO == "nonempty_environments":
            thread["environments"] = [{"environmentId": "host", "cwd": "/workspace"}]
        answer(req, {"thread": thread})
    elif method == "turn/start":
        answer(req, {"turn": {"id": "turn-1", "status": "inProgress", "items": []}})
        base = {"threadId": "thread-1", "turnId": "turn-1"}
        if SCENARIO == "eof":
            sys.exit(0)
        if SCENARIO == "turn_timeout":
            time.sleep(30)
        if SCENARIO in ("tool", "unknown_tool", "approval", "wrong_tool_turn", "large_arguments"):
            params = dict(base, callId="call-1", namespace=None, tool="workspace_read", arguments={"path": "file.txt"})
            if SCENARIO == "unknown_tool": params["tool"] = "exec"
            if SCENARIO == "wrong_tool_turn": params["turnId"] = "other"
            if SCENARIO == "large_arguments": params["arguments"] = {"path": "x" * 65537}
            emit({"id": "server-1", "method": "item/commandExecution/requestApproval" if SCENARIO == "approval" else "item/tool/call", "params": params})
        elif SCENARIO == "event_flood":
            for i in range(70):
                note("item/agentMessage/delta", dict(base, itemId="i", delta="x" * 20000))
        else:
            if SCENARIO == "summary":
                note("item/reasoning/summaryTextDelta", dict(base, itemId="thought-1", summaryIndex=0, delta="Checking the request."))
                breakdown = {"cachedInputTokens": 3, "inputTokens": 11, "outputTokens": 4,
                             "reasoningOutputTokens": 1, "totalTokens": 15, "cacheWriteInputTokens": 0}
                note("thread/tokenUsage/updated", dict(base, tokenUsage={"last": breakdown, "total": breakdown}))
            for delta in ("Hello ", "world"):
                note("item/agentMessage/delta", dict(base, itemId="message-1", delta=delta))
            status = SCENARIO if SCENARIO in ("failed", "interrupted") else "completed"
            note("turn/completed", {"threadId": "thread-1", "turn": {"id": "turn-1", "status": status, "items": [], "error": {"message": "SECRET"} if status == "failed" else None}})
'''


TOOLS = [{"type": "function", "function": {"name": "workspace_read",
    "description": "Read through the existing owner", "parameters": {"type": "object",
    "properties": {"path": {"type": "string"}}, "required": ["path"]}}}]
MESSAGES = [{"role": "system", "content": "system-imported"},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "prior", "type": "function", "function": {"name": "workspace_read", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "prior", "content": "external-result"}]


def connector(tmp_path, scenario="normal", *, timeout_s=2):
    executable = tmp_path / "fake-codex"
    executable.write_text(f"#!{sys.executable}\n" + FAKE.replace("__SCENARIO__", repr(scenario)))
    executable.chmod(0o700)
    return CodexConnector(str(executable), tmp_path / "managed", timeout_s=timeout_s)


def requests(connection):
    path = connection.home / "requests.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_constructor_is_pure_and_rejects_ambient_executable(tmp_path):
    connection = connector(tmp_path)
    assert not connection.home.exists()
    with pytest.raises(CodexConnectorError):
        CodexConnector("codex", connection.home)
    with pytest.raises(CodexConnectorError):
        CodexConnector(str(tmp_path / "fake-codex"), Path.home() / ".codex")


def test_hardened_environment_exact_argv_and_private_config(tmp_path, monkeypatch):
    for key in ("OPENAI_API_KEY", "CHATGPT_TOKEN", "CODEX_AUTH", "CODEX_HOME", "PYTHONPATH", "LD_PRELOAD"):
        monkeypatch.setenv(key, "DO_NOT_INHERIT")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.invalid:8080")
    monkeypatch.setenv("SSL_CERT_FILE", "/tmp/fake-ca.pem")
    connection = connector(tmp_path)
    async def run():
        async with connection:
            assert await connection.account() == {"authenticated": True, "method": "chatgpt", "plan": "plus"}
            assert await connection.models() == ["m1", "m2"]
    asyncio.run(run())
    child = json.loads((connection.home / "child.json").read_text())
    assert child["argv"] == ["app-server", "--listen", "stdio://"]
    assert child["cwd"] == child["home"] == str(connection.home)
    assert child["proxy"] == "http://proxy.example.invalid:8080"
    assert child["ca"] == "/tmp/fake-ca.pem"
    assert not set(child["keys"]) & {"OPENAI_API_KEY", "CHATGPT_TOKEN", "CODEX_AUTH", "PYTHONPATH", "LD_PRELOAD"}
    assert child["path"] != str(tmp_path)
    assert connection.home.stat().st_mode & 0o777 == 0o700
    config = (connection.home / "config.toml").read_text()
    assert 'cli_auth_credentials_store = "keyring"' in config
    assert 'forced_login_method = "chatgpt"' in config
    for flag in ("shell_tool", "multi_agent", "skill_mcp_dependency_install", "enable_mcp_apps", "plugins"):
        assert flag + " = false" in config
    assert (connection.home / "config.toml").stat().st_mode & 0o777 == 0o600
    assert requests(connection)[0]["params"]["capabilities"] == {"experimentalApi": True}
    assert not (connection.home / "auth.json").exists()
    assert connection._process.returncode is not None
    assert __import__("os").environ["CODEX_HOME"] == "DO_NOT_INHERIT"


@pytest.mark.parametrize("method,scenario", [("browser", "normal"), ("device", "normal"), ("browser", "early_login")])
def test_login_challenges_stay_in_memory_and_wait_verifies_chatgpt(tmp_path, method, scenario):
    connection = connector(tmp_path, scenario)
    async def run():
        async with connection:
            challenge = await connection.start_login(method)
            assert challenge["method"] == method and challenge["login_id"] == "login-1"
            if method == "device":
                assert challenge["user_code"] == "ABCD-EFGH"
            assert await connection.wait_login(challenge["login_id"]) is True
    asyncio.run(run())
    persisted = "\n".join(path.read_text() for path in connection.home.iterdir() if path.is_file())
    for secret in ("CHALLENGE", "ABCD-EFGH", "private@example.invalid", "SECRET"):
        assert secret not in persisted


@pytest.mark.parametrize("url", ["http://auth.openai.com/login", "https://auth.openai.com.evil.invalid/login",
    "https://user:password@auth.openai.com/login", "https://chatgpt.com:444/login",
    "https://evil.invalid/login", "https://chatgpt.com\\@evil.invalid/login", "https://chatgpt.com/\nsecret"])
def test_invalid_auth_destinations_fail_closed(tmp_path, url):
    connection = connector(tmp_path, "bad_url:" + url)
    async def run():
        async with connection:
            with pytest.raises(CodexConnectorError) as exc:
                await connection.start_login("browser")
            assert url not in str(exc.value)
            assert connection._process.returncode is not None
    asyncio.run(run())


@pytest.mark.parametrize("scenario", ["login_denied", "api_account", "wrong_login_type"])
def test_denied_or_api_key_login_cannot_establish_subscription(tmp_path, scenario):
    connection = connector(tmp_path, scenario)
    async def run():
        async with connection:
            with pytest.raises(CodexConnectorError) as exc:
                challenge = await connection.start_login("browser")
                await connection.wait_login(challenge["login_id"])
            assert "SECRET" not in str(exc.value)
            assert connection._process.returncode is not None
    asyncio.run(run())


def test_cancel_login_and_logout_close_child(tmp_path):
    connection = connector(tmp_path, "pending_login")
    async def run():
        async with connection:
            challenge = await connection.start_login("device")
            await connection.cancel_login(challenge["login_id"])
            assert connection._process.returncode is not None
            assert connection._logins == {}
        other = connector(tmp_path)
        async with other:
            await other.logout()
            assert other._process.returncode is not None
        assert requests(other)[-1]["method"] == "account/logout"
    asyncio.run(run())


def test_text_stream_and_transcript_boundaries(tmp_path):
    connection = connector(tmp_path)
    chunks = []
    async def run():
        async with connection:
            result = await connection.complete("m1", MESSAGES, TOOLS, lambda kind, text: chunks.append((kind, text)))
            assert result == {"text": "Hello world", "tool_calls": []}
    asyncio.run(run())
    assert chunks == [("content", "Hello "), ("content", "world")]
    thread = next(r["params"] for r in requests(connection) if r.get("method") == "thread/start")
    turn = next(r["params"] for r in requests(connection) if r.get("method") == "turn/start")
    assert thread["environments"] == turn["environments"] == []
    assert turn["summary"] == "auto"
    assert thread["ephemeral"] is True and thread["sandbox"] == "read-only"
    assert thread["approvalPolicy"] == turn["approvalPolicy"] == "untrusted"
    assert thread["allowProviderModelFallback"] is False
    assert "system-imported" not in thread["baseInstructions"] + thread["developerInstructions"]
    assert len(turn["input"]) == 1 and turn["input"][0]["type"] == "text"
    assert json.loads(turn["input"][0]["text"]) == {"messages": MESSAGES}
    assert thread["dynamicTools"][0] == {"type": "function", "name": "workspace_read",
        "description": TOOLS[0]["function"]["description"], "inputSchema": TOOLS[0]["function"]["parameters"]}


def test_dynamic_call_returns_one_openai_call_and_stops_before_execution(tmp_path):
    connection = connector(tmp_path, "tool")
    async def run():
        async with connection:
            result = await connection.complete("m1", MESSAGES, TOOLS)
            assert result == {"text": "", "tool_calls": [{"id": "call-1", "type": "function",
                "function": {"name": "workspace_read", "arguments": '{"path":"file.txt"}'}}]}
            assert connection._process.returncode is not None
    asyncio.run(run())
    assert not any(r.get("id") == "server-1" for r in requests(connection))


@pytest.mark.parametrize("scenario", ["missing_environments", "nonempty_environments"])
def test_unsupported_empty_environments_never_start_turn(tmp_path, scenario):
    connection = connector(tmp_path, scenario)
    async def run():
        async with connection:
            with pytest.raises(CodexConnectorError):
                await connection.complete("m1", MESSAGES)
    asyncio.run(run())
    assert not any(r.get("method") == "turn/start" for r in requests(connection))


@pytest.mark.parametrize("scenario", ["unknown_tool", "approval", "wrong_tool_turn", "large_arguments",
    "failed", "interrupted", "eof", "event_flood", "signed_out", "api_account"])
def test_unauthorized_requests_and_failed_turns_fail_closed(tmp_path, scenario):
    connection = connector(tmp_path, scenario)
    async def run():
        async with connection:
            with pytest.raises(CodexConnectorError) as exc:
                await connection.complete("m1", MESSAGES, TOOLS)
            assert "SECRET" not in str(exc.value) and exc.value.body == ""
            assert connection._process.returncode is not None
    asyncio.run(run())


@pytest.mark.parametrize("scenario", ["malformed", "oversized", "nonfinite", "wrong_home", "rpc_error"])
def test_bad_frames_and_protocol_incompatibility_are_sanitized(tmp_path, scenario):
    connection = connector(tmp_path, scenario)
    async def run():
        with pytest.raises(CodexConnectorError) as exc:
            async with connection:
                pass
        assert "SECRET" not in str(exc.value) and exc.value.body == ""
        assert connection._process.returncode is not None
    asyncio.run(run())


@pytest.mark.parametrize("scenario", ["timeout", "ignore_terminate", "turn_timeout", "pending_login"])
def test_deadlines_kill_and_reap_process(tmp_path, scenario):
    connection = connector(tmp_path, scenario, timeout_s=0.15)
    async def run():
        with pytest.raises(CodexConnectorError):
            async with connection:
                if scenario == "turn_timeout":
                    await connection.complete("m1", MESSAGES)
                elif scenario == "pending_login":
                    challenge = await connection.start_login("device")
                    await connection.wait_login(challenge["login_id"])
        assert connection._process.returncode is not None
    asyncio.run(run())


def test_cancellation_and_external_revocation_close_child(tmp_path):
    connection = connector(tmp_path, "turn_timeout")
    async def run():
        async with connection:
            task = asyncio.create_task(connection.complete("m1", MESSAGES))
            while not any(r.get("method") == "turn/start" for r in requests(connection)):
                await asyncio.sleep(0.005)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert connection._process.returncode is not None
        other = connector(tmp_path, "pending_login")
        async with other:
            challenge = await other.start_login("browser")
            waiter = asyncio.create_task(other.wait_login(challenge["login_id"]))
            await asyncio.sleep(0)
            await other.close()
            with pytest.raises(CodexConnectorError):
                await waiter
            assert other._process.returncode is not None
    asyncio.run(run())


def test_stderr_is_drained_without_rendering(tmp_path, capsys):
    connection = connector(tmp_path, "stderr")
    async def run():
        async with connection:
            await connection.account()
    asyncio.run(run())
    captured = capsys.readouterr()
    assert "SECRET" not in captured.out + captured.err


def test_symlink_home_and_config_are_rejected(tmp_path):
    connection = connector(tmp_path)
    actual = tmp_path / "actual"
    actual.mkdir()
    connection.home.symlink_to(actual, target_is_directory=True)
    async def reject():
        with pytest.raises(CodexConnectorError):
            async with connection:
                pass
        assert connection._process is None
    asyncio.run(reject())
    connection.home.unlink()
    connection.home.mkdir()
    target = tmp_path / "untouched"
    target.write_text("unchanged")
    (connection.home / "config.toml").symlink_to(target)
    connection = connector(tmp_path)
    asyncio.run(reject())
    assert target.read_text() == "unchanged"


def test_auto_model_resolves_from_the_live_catalog(tmp_path):
    connection = connector(tmp_path)
    async def run():
        async with connection:
            await connection.complete('auto', MESSAGES)
    asyncio.run(run())
    thread = next(r['params'] for r in requests(connection) if r.get('method') == 'thread/start')
    assert thread['model'] == 'm1'


def test_official_published_reasoning_summary_and_usage_are_reported():
    connection = connector(Path(__import__('tempfile').mkdtemp()), "summary")
    chunks=[]
    async def run():
        async with connection:
            response=await connection.complete("m1",MESSAGES,TOOLS,lambda kind,text:chunks.append((kind,text)))
            assert response["usage"]=={"prompt_tokens":11,"completion_tokens":4}
            assert response["text"]=="Hello world"
    asyncio.run(run())
    assert chunks==[("reasoning","Checking the request."),("content","Hello "),("content","world")]
