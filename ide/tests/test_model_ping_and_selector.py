"""Tests for top-bar model selector, live pong ping, and persisted latency/error."""

from __future__ import annotations

import asyncio
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from core.agent.providers.base import CompletionResponse
from core.provider_service import ModelPingStore, PingResult, ProviderService
from ui.app import AppController
from ui.main_window import MainWindow


class _FakeOkProvider:
    async def stream_completion(self, messages, tools=None):
        yield SimpleNamespace(kind="text", text="pong", response=None)
        yield SimpleNamespace(kind="completed", text="", response=CompletionResponse(content="pong"))

    async def close(self):
        return None


class _FakeFailProvider:
    async def stream_completion(self, messages, tools=None):
        raise RuntimeError("HTTP 429: rate limit exceeded")
        yield  # pragma: no cover

    async def close(self):
        return None


class _FakeRegistry:
    def __init__(self, provider_obj):
        self._provider_obj = provider_obj

    def get(self, name, model=None):
        return self._provider_obj


def test_model_ping_store_and_service_ok_and_error(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    store = ModelPingStore()

    svc_ok = ProviderService(_FakeRegistry(_FakeOkProvider()))
    res_ok = asyncio.run(svc_ok.ping_model("nvidia", "nvidia/nemotron-3-ultra-550b-a55b", store=store))
    assert res_ok.ok is True
    assert res_ok.latency_ms >= 1
    assert "pong" in res_ok.reply.lower()
    saved_ok = store.get("nvidia", "nvidia/nemotron-3-ultra-550b-a55b")
    assert saved_ok is not None
    assert saved_ok["ok"] is True
    assert saved_ok["latency_ms"] == res_ok.latency_ms

    svc_fail = ProviderService(_FakeRegistry(_FakeFailProvider()))
    res_fail = asyncio.run(svc_fail.ping_model("nvidia", "bad-model", store=store))
    assert res_fail.ok is False
    assert "429" in res_fail.error
    saved_fail = store.get("nvidia", "bad-model")
    assert saved_fail is not None
    assert saved_fail["ok"] is False
    assert "429" in saved_fail["error"]


def test_main_window_model_selector_and_ping_badge(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    app = QApplication.instance() or QApplication([])
    store = ModelPingStore()
    store.record(PingResult("nvidia", "model-a", True, 245, reply="pong"))
    store.record(PingResult("nvidia", "model-b", False, 1200, error="HTTP 503 unavailable"))

    ctrl = AppController(str(tmp_path))
    win = MainWindow(controller=ctrl)
    win.provider_combo.blockSignals(True)
    win.provider_combo.clear()
    win.provider_combo.addItem("nvidia · API", "nvidia")
    win.provider_combo.setCurrentIndex(0)
    win.provider_combo.blockSignals(False)

    win._on_models_discovered("nvidia", ["model-a", "model-b"])
    assert win.model_combo.findText("model-a") >= 0
    assert win.model_combo.findText("model-b") >= 0

    win.model_combo.setCurrentText("model-a")
    win._refresh_ping_badge()
    assert win.model_ping_badge_action.isVisible() is True
    assert "245 ms" in win.model_ping_badge.text()

    win.model_combo.setCurrentText("model-b")
    win._refresh_ping_badge()
    assert win.model_ping_badge_action.isVisible() is True
    assert "✗" in win.model_ping_badge.text()
    assert "503" in win.model_ping_badge.toolTip()
    win.close()
