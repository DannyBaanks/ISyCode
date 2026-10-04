"""Session-local images; transport payloads are bound to provider requests."""
import base64
import re

_CAPABILITIES: dict[tuple[str, str], bool] = {}

def record_image_capability(provider, model, entry):
    architecture = entry.get("architecture")
    architecture = architecture if isinstance(architecture, dict) else {}
    modalities = entry.get("inputModalities") or entry.get("input_modalities") or architecture.get("input_modalities")
    if isinstance(modalities, list):
        _CAPABILITIES[(provider, model)] = "image" in modalities

def accepts_images(provider, model):
    if (provider, model) in _CAPABILITIES:
        return _CAPABILITIES[(provider, model)]
    if provider == "openai" and model == "gpt-6-luna":
        return True
    if provider == "anthropic":
        from isycode.anthropic_provider import ADAPTIVE_THINKING_MODELS
        return model in ADAPTIVE_THINKING_MODELS
    return False

class ImageAttachments:
    def __init__(self):
        self.items = {}
        self.sequence = 0

    def capture(self, mime, data):
        signatures = {"image/png": data.startswith(b"\x89PNG\r\n\x1a\n"), "image/jpeg": data.startswith(b"\xff\xd8\xff"), "image/gif": data.startswith((b"GIF87a", b"GIF89a")), "image/webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP"}
        if not signatures.get(mime) or len(data) > 8 * 1024 * 1024:
            raise ValueError("unsupported or invalid image")
        self.sequence += 1
        label = f"[IMAGE#{self.sequence}]"
        self.items[label] = (mime, bytes(data))
        return label

    def content(self, text):
        labels = list(dict.fromkeys(re.findall(r"\[IMAGE#\d+\]", text)))
        if not labels:
            return text
        if any(label not in self.items for label in labels):
            raise ValueError("Image attachment unavailable; paste it again before sending")
        content = [{"type": "text", "text": text}]
        for label in labels:
            mime, data = self.items[label]
            content.append({"type": "text", "text": label})
            content.append({"type": "image_url", "image_url": {"url": "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")}})
        return content

    def prepare(self, messages, provider, model):
        result = []
        for message in messages:
            copied = dict(message)
            text = copied.get("content")
            if copied.get("role") == "user" and isinstance(text, str) and re.search(r"\[IMAGE#\d+\]", text):
                if not accepts_images(provider, model):
                    raise ValueError("This model has no verified image support; choose a vision model or remove the image")
                copied["content"] = self.content(text)
            result.append(copied)
        return result
