"""Qt -> actual local HTTP streaming -> reviewed write -> durable chat."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ui.app import AppController
from ui.main_window import MainWindow


@pytest.mark.parametrize("approved", [False, True])
def test_daily_chat_change_and_resume(qtbot, tmp_path, approved):
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(data)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            if len(calls) == 1:
                chunks = [{"choices": [{"delta": {"content": "Revisa este cambio.", "tool_calls": [{"index": 0, "id": "fixture-call", "type": "function", "function": {"name": "write", "arguments": json.dumps({"path": "app.py", "content": "reviewed change\n"})}}]}, "finish_reason": None}]},
                          {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}]
            else:
                chunks = [{"choices": [{"delta": {"content": "Turno terminado."}, "finish_reason": None}]},
                          {"choices": [{"delta": {}, "finish_reason": "stop"}]}]
            for chunk in chunks:
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("original\n")
    controller = AppController(project)
    controller.add_provider("fixture-local", "openai-compatible", "fixture-model",
                            endpoint=f"http://127.0.0.1:{server.server_port}/v1", auth="none")
    window = MainWindow(controller)
    qtbot.addWidget(window)
    window.show()
    try:
        window._set_mode("coder")
        window.chat.prompt_submitted.emit("Revisa y cambia el saludo")
        qtbot.waitUntil(lambda: window.chat._active_approval_card is not None, timeout=10000)
        card = window.chat._active_approval_card
        assert "reviewed change" in card.diff
        assert (project / "app.py").read_text() == "original\n"
        (card.approve_button if approved else card.reject_button).click()
        qtbot.waitUntil(lambda: not window._agent_busy(), timeout=10000)
        assert len(calls) == 2
        tool = next(message for message in calls[1]["messages"] if message["role"] == "tool")
        assert json.loads(tool["content"])["success"] is approved
        assert (project / "app.py").read_text() == ("reviewed change\n" if approved else "original\n")
        session = window._session_id
        assert controller.conversations.turn_status(session) == "completed"
        events = controller.conversations.events(session)
        assert any(event["payload"].get("status") == ("applied" if approved else "rejected") for event in events)
        window.close()
        reopened = MainWindow(AppController(project))
        qtbot.addWidget(reopened)
        assert reopened._session_id == session
        assert any("Turno terminado" in row["content"] for row in reopened.controller.conversations.transcript(session))
        reopened.close()
    finally:
        window.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_cancelled_http_turn_preserves_partial_reply(qtbot, tmp_path):
    release = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"Respuesta parcial"},"finish_reason":null}]}\n\n')
            self.wfile.flush()
            release.wait(5)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    controller = AppController(tmp_path)
    controller.add_provider("local", "openai-compatible", "fixture-model", endpoint=f"http://127.0.0.1:{server.server_port}/v1", auth="none")
    window = MainWindow(controller)
    qtbot.addWidget(window)
    window.show()
    try:
        window.chat.prompt_submitted.emit("stream fixture")
        qtbot.waitUntil(lambda: window.chat._streaming_bubble is not None and "parcial" in window.chat._streaming_bubble._buffer, timeout=5000)
        window._stop_agent()
        qtbot.waitUntil(lambda: not window._agent_busy(), timeout=5000)
        assert controller.conversations.turn_status(window._session_id) == "cancelled"
        assert any("Respuesta parcial" in message["content"] for message in controller.conversations.transcript(window._session_id))
    finally:
        release.set()
        window.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
