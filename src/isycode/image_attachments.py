"""Session-local images; transport payloads are bound to provider requests."""
import atexit
import base64
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile

_CAPABILITIES: dict[tuple[str, str], bool] = {}

_MIME_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

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


def labels_in_messages(messages) -> list[str]:
    """Return unique [IMAGE#n] labels referenced by user messages in order."""
    found: list[str] = []
    seen: set[str] = set()
    for message in messages:
        if message.get("role") != "user":
            continue
        content = message.get("content")
        texts = []
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    texts.append(str(part.get("text") or ""))
        for chunk in texts:
            for label in re.findall(r"\[IMAGE#\d+\]", chunk):
                if label not in seen:
                    seen.add(label)
                    found.append(label)
    return found


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
        self._stage_dir: Path | None = None
        self._staged_paths: dict[str, Path] = {}

    def capture(self, mime, data):
        signatures = {"image/png": data.startswith(b"\x89PNG\r\n\x1a\n"), "image/jpeg": data.startswith(b"\xff\xd8\xff"), "image/gif": data.startswith((b"GIF87a", b"GIF89a")), "image/webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP"}
        if not signatures.get(mime) or len(data) > 8 * 1024 * 1024:
            raise ValueError("unsupported or invalid image")
        self.sequence += 1
        label = f"[IMAGE#{self.sequence}]"
        self.items[label] = (mime, bytes(data))
        return label

    def stage_for_labels(self, labels) -> list[dict[str, object]]:
        """Write captured image bytes to a session-private 0700/0600 temp dir for FlowSight inspection."""
        staged: list[dict[str, object]] = []
        valid = [label for label in labels if label in self.items]
        if not valid:
            return staged
        if self._stage_dir is None or not self._stage_dir.is_dir():
            tmp = Path(tempfile.mkdtemp(prefix="isycode-img-"))
            if os.name == "posix":
                try:
                    os.chmod(tmp, 0o700)
                except OSError:
                    pass
            self._stage_dir = tmp
            atexit.register(self.cleanup)
        for label in valid:
            mime, data = self.items[label]
            path = self._staged_paths.get(label)
            if path is None or not path.is_file():
                num = re.sub(r"[^0-9]", "", label) or str(len(self._staged_paths) + 1)
                ext = _MIME_EXT.get(mime, ".png")
                path = self._stage_dir / f"image_{num}{ext}"
                path.write_bytes(data)
                if os.name == "posix":
                    try:
                        os.chmod(path, 0o600)
                    except OSError:
                        pass
                self._staged_paths[label] = path
            staged.append({
                "label": label,
                "path": str(path),
                "mime": mime,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            })
        return staged

    def cleanup(self) -> None:
        """Remove session-private staged image files."""
        stage_dir = self._stage_dir
        self._stage_dir = None
        self._staged_paths.clear()
        if stage_dir is not None and stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)

    def content_for_label(self, label: str, caption: str):
        """Build a multimodal content list for one captured label without parsing ``caption``."""
        if label not in self.items:
            raise ValueError("Image attachment unavailable; paste it again before sending")
        mime, data = self.items[label]
        return [
            {"type": "text", "text": caption},
            {"type": "image_url", "image_url": {"url": "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")}},
        ]

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

    def without_images(self, messages, *, blind_guidance: str | None = None):
        """Copy of the turn with image payloads removed and the question kept."""
        result = []
        last_img_idx: int | None = None
        for idx, message in enumerate(messages):
            copied = dict(message)
            text = copied.get("content")
            if copied.get("role") == "user" and isinstance(text, str) and re.search(r"\[IMAGE#\d+\]", text):
                copied["content"] = plain_prompt(text)
                last_img_idx = idx
            elif copied.get("role") == "user" and isinstance(text, list):
                words = [str(part.get("text") or "") for part in text
                         if isinstance(part, dict) and part.get("type") == "text"]
                copied["content"] = plain_prompt("\n".join(words))
                last_img_idx = idx
            result.append(copied)
        if blind_guidance and last_img_idx is not None:
            result[last_img_idx]["content"] = (
                f"{result[last_img_idx]['content']}\n\n{blind_guidance.strip()}"
            )
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
