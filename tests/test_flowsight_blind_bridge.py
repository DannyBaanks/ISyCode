"""Tests for ISyCode FlowSight blind-vision fallback + private staging + ask_user prompt."""
from __future__ import annotations

import base64
import os
from pathlib import Path
import stat

from isycode.flowsight_bridge import build_blind_image_guidance
from isycode.image_attachments import ImageAttachments, labels_in_messages, plain_prompt

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII="
)


def test_stage_for_labels_creates_private_file_and_cleans_up():
    images = ImageAttachments()
    label = images.capture("image/png", PNG)
    staged = images.stage_for_labels([label])
    assert len(staged) == 1
    p = Path(str(staged[0]["path"]))
    assert p.is_file()
    assert p.read_bytes() == PNG
    if os.name == "posix":
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
        assert stat.S_IMODE(p.parent.stat().st_mode) == 0o700
    stage_dir = p.parent
    images.cleanup()
    assert not p.exists()
    assert not stage_dir.exists()


def test_blind_guidance_includes_flowsight_ask_user_and_private_failure_corpus():
    images = ImageAttachments()
    try:
        label = images.capture("image/png", PNG)
        msgs = [{"role": "user", "content": f"{label} qué botón verde ves?"}]
        assert labels_in_messages(msgs) == [label]

        # Default without_images() remains 100% backward compatible
        plain_only = images.without_images(msgs)
        assert plain_only[0]["content"] == plain_prompt(msgs[0]["content"])

        # With FlowSight blind guidance attached
        staged = images.stage_for_labels([label])
        guidance = build_blind_image_guidance(staged, mcp_running=True, mcp_configured=True)
        enriched = images.without_images(msgs, blind_guidance=guidance)
        body = enriched[0]["content"]
        assert isinstance(body, str)
        assert "image_url" not in body
        assert "qué botón verde ves?" in body
        assert str(staged[0]["path"]) in body
        assert "mcp__flowsight__flowsight_screen_run" in body
        assert "ask_user" in body
        assert "DEMONSTRATED" in body and "INFERRED" in body
        assert "flowsight_log_failure" in body
    finally:
        images.cleanup()
