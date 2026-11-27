"""Tests for universal attachment staging, semantic extension-to-tool RAG, and ChatPanel preview strip."""

from __future__ import annotations

import json
import os
import struct
import zipfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from core.attachment_router import (
    build_hidden_attachment_prompt,
    inspect_attachment,
    route_attachment,
    stage_attachment,
)
from ui.panels.chat import ChatPanel


def _make_tiny_png() -> bytes:
    # Minimal valid PNG header with 16x12 IHDR dimensions
    ihdr_data = struct.pack(">IIBBBBB", 16, 12, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr_data + b"\x00\x00\x00\x00"


def test_semantic_extension_router_covers_all_categories(tmp_path):
    assert route_attachment(tmp_path / "shot.png").category == "image"
    assert "flowsight" in route_attachment(tmp_path / "shot.png").mcp_servers
    assert "IGNORA FlowSight" in route_attachment(tmp_path / "shot.png").instruction

    assert route_attachment(tmp_path / "clip.mp4").mcp_servers == ("isymcp-media",)
    assert "office-bridge" in route_attachment(tmp_path / "doc.pdf").mcp_servers
    assert route_attachment(tmp_path / "app.exe").mcp_servers == ("rea",)
    assert route_attachment(tmp_path / "bundle.zip").category == "archive"
    assert route_attachment(tmp_path / "script.py").category == "code"
    assert route_attachment(tmp_path / "mystery.xyz123").category == "other"


def test_stage_inspect_and_hidden_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    ws = tmp_path / "repo"
    ws.mkdir()

    # Stage pasted PNG bytes -> stored outside repo working tree (git-clean!)
    staged_png = stage_attachment(ws, raw_bytes=_make_tiny_png(), filename="captura.png")
    assert staged_png.is_file()
    assert not (ws / "captura.png").exists()

    res_png = inspect_attachment(ws, str(staged_png))
    assert res_png.success
    data_png = json.loads(res_png.stdout)
    assert data_png["dimensions"] == {"width": 16, "height": 12}
    assert data_png["route"]["category"] == "image"

    # Stage a ZIP archive and inspect entries safely
    zpath = tmp_path / "pack.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("hello.txt", "world")
    staged_zip = stage_attachment(ws, source_path=zpath)
    res_zip = inspect_attachment(ws, str(staged_zip))
    assert res_zip.success
    data_zip = json.loads(res_zip.stdout)
    assert "hello.txt" in data_zip["zip_entries_preview"]

    hidden = build_hidden_attachment_prompt([staged_png, staged_zip])
    assert "HIDDEN ATTACHMENT TOOL-ROUTER" in hidden
    assert "flowsight" in hidden
    assert "pack.zip" in hidden


def test_chat_panel_attachments_strip_preview_and_take(tmp_path):
    app = QApplication.instance() or QApplication([])
    chat = ChatPanel()
    assert chat.attachments_strip.isHidden() is True

    sample_file = tmp_path / "notes.pdf"
    sample_file.write_bytes(b"%PDF-1.4\n")
    chat.attach_image_bytes(_make_tiny_png(), "screen.png")
    chat.attach_files([str(sample_file)])
    assert chat.attachments_strip.isHidden() is False
    assert len(chat._pending_attachments) == 2

    taken = chat.take_pending_attachments()
    assert len(taken) == 2
    assert chat.attachments_strip.isHidden() is True
