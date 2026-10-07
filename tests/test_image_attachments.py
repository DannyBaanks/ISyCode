import base64
import pytest
from isycode.image_attachments import ImageAttachments, record_image_capability
from isycode.anthropic_provider import to_anthropic

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII=")

def test_image_is_real_payload_and_unknown_support_can_be_tried(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    images = ImageAttachments()
    label = images.capture("image/png", PNG)
    assert label == "[IMAGE#1]"
    messages = [{"role": "user", "content": "Explain " + label}]
    assert images.prepare(messages, "nvidia", "unknown")[0]["content"][-1]["type"] == "image_url"
    record_image_capability("test", "text-only", {"inputModalities": ["text"]})
    with pytest.raises(ValueError, match="no image support"):
        images.prepare(messages, "test", "text-only")
    record_image_capability("test", "vision", {"inputModalities": ["text", "image"]})
    result = images.prepare(messages, "test", "vision")
    url = result[0]["content"][-1]["image_url"]["url"]
    assert base64.b64decode(url.split(",")[1]) == PNG
    assert messages[0]["content"] == "Explain " + label
    _, anthropic = to_anthropic(result)
    assert anthropic[0]["content"][-1]["source"]["media_type"] == "image/png"
    assert base64.b64decode(anthropic[0]["content"][-1]["source"]["data"]) == PNG


def test_missing_or_invalid_images_are_not_fake_attachments():
    images = ImageAttachments()
    with pytest.raises(ValueError):
        images.capture("image/png", b"not an image")
    with pytest.raises(ValueError, match="unavailable"):
        images.content("[IMAGE#1]")
    assert images.content("plain text") == "plain text"


def test_image_turn_can_continue_as_text_once():
    from isycode.image_attachments import image_failure_should_continue, plain_prompt
    from isycode.providers import ProviderError
    from isycode.streaming import StreamError

    images = ImageAttachments()
    label = images.capture("image/png", PNG)
    original = [{"role": "user", "content": f"{label} puedes ver la imagen?"}]
    stripped = images.without_images(images.prepare(original, "openai", "unknown"))
    assert isinstance(stripped[0]["content"], str)
    assert "image_url" not in stripped[0]["content"]
    assert stripped[0]["content"] == plain_prompt(original[0]["content"])
    assert original[0]["content"].startswith("[IMAGE#")
    broken = StreamError("provider closed an incomplete completion stream")
    assert image_failure_should_continue(broken, sent=True, used=False, saw_output=False)
    assert not image_failure_should_continue(broken, sent=True, used=True, saw_output=False)
    assert not image_failure_should_continue(broken, sent=True, used=False, saw_output=True)
    assert not image_failure_should_continue(
        ProviderError("connection failed", transport=True), sent=True, used=False, saw_output=False)
    assert not image_failure_should_continue(
        ProviderError("rejected", status=401), sent=True, used=False, saw_output=False)


def test_clipboard_read_is_denied_before_os_access(tmp_path, monkeypatch):
    from isycode.clipboard_owner import ClipboardOwner
    from isycode.workspace_authority import WorkspaceAuthority
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "project"
    root.mkdir()
    authority = WorkspaceAuthority(root)
    def unexpected():
        pytest.fail("clipboard read before grant")
    monkeypatch.setattr("isycode.clipboard_owner.read_system_clipboard", unexpected)
    outcome, mime, data = ClipboardOwner(root, authority).paste()
    assert outcome.decision == "DENY" and not mime and not data


def test_clipboard_read_has_receipt_and_keeps_payload_out_of_journal(tmp_path, monkeypatch):
    from isycode.clipboard_owner import ClipboardOwner
    from isycode.workspace_authority import WorkspaceAuthority
    from isycode.action_audit import ActionAuditJournal
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "project"
    root.mkdir()
    authority = WorkspaceAuthority(root)
    authority.set_grant("clipboard.paste", enabled=True, targets=["clipboard"])
    monkeypatch.setattr("isycode.clipboard_owner.read_system_clipboard", lambda: ("image/png", PNG))
    outcome, mime, data = ClipboardOwner(root, authority).paste()
    assert outcome.decision == "ALLOW" and outcome.receipt and data == PNG
    assert ActionAuditJournal(root).verify().receipts == 1
    assert base64.b64encode(PNG).decode() not in ActionAuditJournal(root).path.read_text()
