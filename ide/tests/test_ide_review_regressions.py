"""Final review regressions: real Git, SDK HTTP and saved selection boundaries."""
import asyncio
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import anthropic
import pytest

from core.agent.providers.anthropic import AnthropicProvider
from core.agent.providers.base import ProviderConfig
from core.agent.chat import IsycoAgentApp
from core.github_service import GitHubError
from tests.test_ide_github import checkout, git
from ui.app import AppController
from ui.main_window import MainWindow


@pytest.mark.parametrize("when", ["before_preview", "after_preview"])
def test_pull_preserves_ignored_incoming_collision(checkout, when):
    root, sync, base, _ = checkout
    git(root, "switch", "incoming")
    (root / "local.txt").write_text("incoming replacement")
    git(root, "add", "local.txt")
    git(root, "commit", "-m", "incoming tracked file")
    target = git(root, "rev-parse", "HEAD")
    git(root, "switch", "local")
    (root / ".git/info/exclude").write_text("local.txt\n")
    original = sync._git
    async def remote(args, **kwargs):
        if args[0] == "fetch":
            git(root, "update-ref", "refs/remotes/upstream/feature", target)
            from core.processes import ProcessOutput
            return ProcessOutput(0, b"", b"")
        if args[0] == "ls-remote":
            from core.processes import ProcessOutput
            return ProcessOutput(0, (target + "\trefs/heads/feature\n").encode(), b"")
        return await original(args, **kwargs)
    sync._git = remote
    async def run():
        if when == "before_preview":
            (root / "local.txt").write_text("keep ignored user data")
            with pytest.raises(GitHubError, match="local|ignorado"):
                await sync.preview_pull("Fixture/project")
        else:
            preview = await sync.preview_pull("Fixture/project")
            (root / "local.txt").write_text("keep ignored user data")
            with pytest.raises(GitHubError, match="local|ignorado"):
                await sync.apply_pull(preview.id, operator_approved=True)
    asyncio.run(run())
    assert git(root, "rev-parse", "HEAD") == base
    assert (root / "local.txt").read_text() == "keep ignored user data"


class Credentials:
    def get(self, name):
        return "synthetic-fixture-key"
    def clear(self):
        pass


@pytest.fixture
def sdk_servers():
    seen = []
    mode = {"redirect": False}
    class Sink(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(("sink", self.headers.get("x-api-key")))
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()
        def log_message(self, *args):
            pass
    sink = ThreadingHTTPServer(("127.0.0.1", 0), Sink)
    class Source(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(("source", request))
            if mode["redirect"]:
                self.send_response(307)
                self.send_header("Location", f"http://127.0.0.1:{sink.server_port}/v1/messages")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            message = {"id": "msg_fixture", "type": "message", "role": "assistant", "model": "fixture",
                       "content": [{"type": "text", "text": "SDK reply"}], "stop_reason": "end_turn",
                       "stop_sequence": None, "usage": {"input_tokens": 3, "output_tokens": 2}}
            if request.get("stream"):
                start = {**message, "content": [], "stop_reason": None}
                events = [
                    {"type": "message_start", "message": start},
                    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "SDK reply"}},
                    {"type": "content_block_stop", "index": 0},
                    {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 2}},
                    {"type": "message_stop"}]
                body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()
                content_type = "text/event-stream"
            else:
                body, content_type = json.dumps(message).encode(), "application/json"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    source = ThreadingHTTPServer(("127.0.0.1", 0), Source)
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (source, sink)]
    for thread in threads:
        thread.start()
    yield f"http://127.0.0.1:{source.server_port}", mode, seen
    for server in (source, sink):
        server.shutdown()
        server.server_close()
    for thread in threads:
        thread.join()


@pytest.mark.parametrize("method", ["complete", "stream_completion", "stream"])
def test_actual_anthropic_sdk_request_contract(sdk_servers, method):
    endpoint, _, seen = sdk_servers
    async def run():
        provider = AnthropicProvider(ProviderConfig("fixture", "anthropic", "fixture", endpoint), Credentials())
        try:
            messages = [{"role": "user", "content": "hello"}]
            if method == "complete":
                assert (await provider.complete(messages)).content == "SDK reply"
            elif method == "stream_completion":
                events = [e async for e in provider.stream_completion(messages)]
                assert events[-1].response.content == "SDK reply"
            else:
                assert "".join([e async for e in provider.stream(messages)]) == "SDK reply"
        finally:
            await provider.close()
    asyncio.run(run())
    assert len(seen) == 1 and seen[0][0] == "source"


@pytest.mark.parametrize("stream", [False, True])
def test_anthropic_sdk_never_forwards_key_to_redirect_origin(sdk_servers, stream):
    endpoint, mode, seen = sdk_servers
    mode["redirect"] = True
    async def run():
        provider = AnthropicProvider(ProviderConfig("fixture", "anthropic", "fixture", endpoint), Credentials())
        try:
            # Actual SDK call without optional parameters isolates transport safety.
            with pytest.raises(anthropic.APIStatusError):
                if stream:
                    async with provider._get_client().messages.stream(model="fixture", max_tokens=8, messages=[{"role": "user", "content": "hello"}]):
                        pass
                else:
                    await provider._get_client().messages.create(model="fixture", max_tokens=8, messages=[{"role": "user", "content": "hello"}])
        finally:
            await provider.close()
    asyncio.run(run())
    assert not any(item[0] == "sink" for item in seen)


@pytest.mark.parametrize("available", [True, False])
def test_qt_resume_restores_or_requires_saved_provider(qtbot, tmp_path, available, monkeypatch):
    controller = AppController(tmp_path)
    controller.provider_registry.add("first-api", "openai", "first-model", api_key="synthetic")
    if available:
        controller.provider_registry.add("saved-local", "ollama", "default-model")
    session = controller.conversations.create(provider="saved-local", model="custom-saved-model")
    widget = MainWindow(controller)
    qtbot.addWidget(widget)
    assert widget._session_id == session
    if available:
        assert widget.provider_combo.currentData() == "saved-local"
        assert widget.model_combo.currentText() == "custom-saved-model"
        widget._refresh_provider_models()
        assert widget.model_combo.currentText() == "custom-saved-model"
        controller.provider_registry.remove("saved-local")
        widget._refresh_provider_models()
        assert widget.provider_combo.currentData() is None
        assert widget._provider_replacement_required
    else:
        monkeypatch.setattr("ui.main_window.AgentWorker", lambda *a, **k: pytest.fail("missing provider must not start inference"))
        widget._start_agent("preserve draft")
        assert widget.chat.input.toPlainText() == "preserve draft"
        assert widget.provider_combo.currentData() is None
        widget.provider_combo.setCurrentIndex(widget.provider_combo.findData("first-api"))
        assert not widget._provider_replacement_required
    widget.close()


@pytest.mark.parametrize("available", [True, False])
def test_tui_resume_restores_or_requires_saved_provider(tmp_path, available, monkeypatch):
    from core.conversations import ConversationStore
    app = IsycoAgentApp(working_dir=str(tmp_path))
    app.provider_registry.add("first-api", "openai", "first-model", api_key="synthetic")
    if available:
        app.provider_registry.add("saved-local", "ollama", "default-model")
    session = ConversationStore(tmp_path).create(provider="saved-local", model="custom-saved-model")
    async def run():
        async with app.run_test():
            app.resume_conversation(session)
            if available:
                assert app.context.provider_name == "saved-local"
                assert app.context.model == "custom-saved-model"
                assert app.status_bar.provider == "saved-local"
            else:
                async def forbidden(*args, **kwargs):
                    pytest.fail("missing provider must not start inference")
                monkeypatch.setattr(app.conversation_service, "run_agent", forbidden)
                await app.run_agent("hello")
                assert app.context.provider_name == ""
                await app.switch_provider("first-api")
                assert not app._provider_replacement_required
    asyncio.run(run())


def test_changed_upstream_with_same_commit_requires_fresh_check(checkout):
    root, sync, _, target = checkout
    async def run():
        assert (await sync.inspect(refresh=True, expected_repo="Fixture/project")).fresh
        git(root, "update-ref", "refs/remotes/upstream/other", target)
        git(root, "config", "branch.local.merge", "refs/heads/other")
        report = await sync.inspect()
        assert report.remote_branch == "other"
        assert report.behind == 1
        assert not report.fresh and report.checked is None
    asyncio.run(run())
