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
    from isycode.capability_observations import observed
    learned = observed(provider, model, "images")
    return learned if learned is not None else _CAPABILITIES.get((provider, model))


def record_image_result(provider, model, supported):
    from isycode.capability_observations import record
    return record(provider, model, "images", supported)


_IMAGE_RETRY_KINDS = {"IMAGES", "STREAM", "REQUEST", "UNKNOWN", "TIMEOUT"}


def plain_prompt(text: str) -> str:
    """The words of a turn after its image labels are removed."""
    cleaned = re.sub(r"\[IMAGE#\d+\]", "", text)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned or "I attached an image, but it could not be sent."


def image_failure_should_continue(exc, *, sent: bool, used: bool, saw_output: bool) -> bool:
    """One text continuation after an image payload dies before any answer.

    Auth, quota, and connection failures are not image failures. A turn that
    already produced text or reasoning is left alone.
    """
    if not sent or used or saw_output:
        return False
    from isycode.provider_errors import classify_provider_error
    return classify_provider_error(exc)["error_kind"] in _IMAGE_RETRY_KINDS

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

    def without_images(self, messages):
        """Copy of the turn with image payloads removed and the question kept."""
        result = []
        for message in messages:
            copied = dict(message)
            text = copied.get("content")
            if copied.get("role") == "user" and isinstance(text, str) and re.search(r"\[IMAGE#\d+\]", text):
                copied["content"] = plain_prompt(text)
            elif copied.get("role") == "user" and isinstance(text, list):
                words = [str(part.get("text") or "") for part in text
                         if isinstance(part, dict) and part.get("type") == "text"]
                copied["content"] = plain_prompt("\n".join(words))
            result.append(copied)
        return result

    def prepare(self, messages, provider, model):
        result = []
        for message in messages:
            copied = dict(message)
            text = copied.get("content")
            if copied.get("role") == "user" and isinstance(text, str) and re.search(r"\[IMAGE#\d+\]", text):
                if accepts_images(provider, model) is False:
                    raise ValueError("This provider/model reports no image support; choose another model or remove the image")
                copied["content"] = self.content(text)
            result.append(copied)
        return result
