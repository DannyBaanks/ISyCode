"""Official Tabler outline assets, vendored with MIT license and provenance."""
from pathlib import Path
from functools import lru_cache
from urllib.parse import urlsplit
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer

NAMES = {"chat": "message-circle", "code": "code", "folder": "folder",
         "changes": "git-branch", "tools": "tool", "tests": "flask",
         "evidence": "file-text", "system": "database", "github": "brand-github",
         "settings": "settings", "terminal": "terminal-2", "provider": "cpu",
         "menu": "menu-2", "search": "search", "plus": "plus"}

@lru_cache(maxsize=128)
def icon(name, color="#adbed1", size=24):
    path = Path(__file__).parent / "assets" / "tabler" / (NAMES.get(name, "folder") + ".svg")
    source = path.read_bytes().replace(b"currentColor", color.encode("ascii"))
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(source).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


@lru_cache(maxsize=128)
def _file_icon(key, size):
    path = Path(__file__).parent / "assets" / "vscode-icons" / (key + ".svg")
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(path.read_bytes()).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


def file_icon(path, is_dir=False, size=22):
    from core.file_icons import file_identity
    return _file_icon(file_identity(str(path), is_dir)[0], size)


# Lobe Icons SVG subset: exact upstream bytes and MIT license in assets/providers.
PROVIDER_ASSETS = {
    "nvidia": "nvidia-color", "openai": "openai", "anthropic": "anthropic",
    "claude": "claude-color", "gemini": "gemini-color", "grok": "grok",
    "groq": "groq", "ollama": "ollama", "lmstudio": "lmstudio",
    "mistral": "mistral-color", "deepseek": "deepseek-color",
    "openrouter": "openrouter-color",
}
PROVIDER_ALIASES = {"google": "gemini", "chatgpt": "openai", "gpt": "openai"}
SUBSCRIPTION_BRANDS = {"codex-subscription": "openai",
                       "claude-subscription": "claude", "grok-subscription": "grok"}
PROVIDER_HOSTS = {
    "api.openai.com": "openai", "api.anthropic.com": "anthropic",
    "generativelanguage.googleapis.com": "gemini",
    "integrate.api.nvidia.com": "nvidia", "openrouter.ai": "openrouter",
    "api.groq.com": "groq", "api.deepseek.com": "deepseek",
    "api.mistral.ai": "mistral", "api.x.ai": "grok",
}


def provider_brand(name="", config=None):
    """Presentation identity, never a statement of authentication or availability.

    Known endpoint hosts take precedence over editable profile names. An unknown
    compatible endpoint stays generic even if it serves GPT/Claude models.
    """
    if config is None:
        return PROVIDER_ALIASES.get(name, name) if isinstance(name, str) else ""
    kind = config.get("provider", "")
    if kind in SUBSCRIPTION_BRANDS:
        return SUBSCRIPTION_BRANDS[kind]
    endpoint = config.get("endpoint", "")
    try:
        host = (urlsplit(endpoint).hostname or "").lower()
    except (ValueError, TypeError):
        return ""
    if host in PROVIDER_HOSTS:
        return PROVIDER_HOSTS[host]
    if kind == "ollama":
        return "ollama"
    # LM Studio is a local OpenAI-compatible transport with no unique host.
    if host in {"localhost", "127.0.0.1", "::1"} and isinstance(name, str):
        alias = name.lower().replace("-", "").replace("_", "")
        if alias == "lmstudio":
            return "lmstudio"
    if not endpoint:
        return PROVIDER_ALIASES.get(kind, kind) if kind != "openai-compatible" else ""
    return ""


@lru_cache(maxsize=96)
def _provider_icon(brand, size):
    path = Path(__file__).parent / "assets" / "providers" / (PROVIDER_ASSETS[brand] + ".svg")
    # Keep colored variants unchanged; currentColor variants need a dark-theme tint.
    source = path.read_bytes().replace(b"currentColor", b"#eef5fc")
    renderer = QSvgRenderer(source)
    if not renderer.isValid():
        return icon("provider", size=size)
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


def provider_icon(name="", config=None, size=22):
    brand = provider_brand(name, config)
    return _provider_icon(brand, size) if brand in PROVIDER_ASSETS else icon("provider", size=size)
