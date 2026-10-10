"""User-visible ISyCode copy. Presentation only; never a grant or protocol."""
from __future__ import annotations

import re
from pathlib import Path

SUPPORTED_LOCALES = ("es", "en")
DEFAULT_LOCALE = "es"
DOMAIN = "isycode"
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}|%\(([A-Za-z_][A-Za-z0-9_]*)\)s")

_LOCALE = DEFAULT_LOCALE
_CATALOG: dict[tuple[str, str], str] = {}
_DIAGNOSTIC = ""
_CATALOG_ROOT: Path | None = None


def current_locale() -> str:
    return _LOCALE


def catalog_diagnostic() -> str:
    return _DIAGNOSTIC


def configure_locale(locale: str, *, catalog_root: Path | None = None) -> None:
    """Load a packaged catalog. A missing Spanish catalog falls back to English."""
    global _LOCALE, _CATALOG, _DIAGNOSTIC, _CATALOG_ROOT
    _CATALOG_ROOT = catalog_root
    wanted = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE
    try:
        catalog = _load_catalog(wanted)
    except (OSError, ValueError, UnicodeDecodeError):
        catalog = {}
    if wanted == "es" and not catalog:
        try:
            catalog = _load_catalog("en")
            _LOCALE = "en"
            _DIAGNOSTIC = "ISyCode could not load the Spanish catalog; showing English."
            _CATALOG = catalog
            return
        except (OSError, ValueError, UnicodeDecodeError):
            _LOCALE = "en"
            _CATALOG = {}
            _DIAGNOSTIC = "ISyCode could not load the Spanish catalog; showing English."
            return
    _LOCALE = wanted
    _CATALOG = catalog
    _DIAGNOSTIC = ""


def tr(message: str, *, context: str | None = None, **values: object) -> str:
    """Return the active-locale rendering of an English source message."""
    template = _CATALOG.get((context or "", message), message)
    if not values:
        return template
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError):
        try:
            return message.format(**values)
        except (KeyError, IndexError, ValueError):
            return message


def validate_catalogs(catalog_root: Path | None = None) -> list[str]:
    """Return problems: missing IDs or placeholder mismatches. Empty means aligned."""
    root = catalog_root or _catalog_root()
    problems: list[str] = []
    try:
        english = _parse_po(_po_path(root, "en").read_text(encoding="utf-8"))
        spanish = _parse_po(_po_path(root, "es").read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as error:
        return [f"catalogs could not be read: {error}"]
    english_ids = set(english)
    spanish_ids = set(spanish)
    for missing in sorted(english_ids - spanish_ids):
        problems.append(f"missing Spanish entry {missing[0]!r} {missing[1]!r}")
    for extra in sorted(spanish_ids - english_ids):
        problems.append(f"extra Spanish entry {extra[0]!r} {extra[1]!r}")
    for key in sorted(english_ids & spanish_ids):
        source = _placeholders(key[1])
        translated = _placeholders(spanish[key])
        if source != translated:
            problems.append(
                f"placeholder mismatch {key[0]!r} {key[1]!r}: {sorted(source)} vs {sorted(translated)}"
            )
    return problems


def _catalog_root() -> Path:
    return _CATALOG_ROOT or Path(__file__).resolve().parent / "locales"


def _po_path(root: Path, locale: str) -> Path:
    return root / locale / "LC_MESSAGES" / f"{DOMAIN}.po"


def _load_catalog(locale: str) -> dict[tuple[str, str], str]:
    path = _po_path(_catalog_root(), locale)
    parsed = _parse_po(path.read_text(encoding="utf-8"))
    return {key: value for key, value in parsed.items() if key[1]}


def _placeholders(text: str) -> set[str]:
    names = set()
    for match in PLACEHOLDER_RE.finditer(text):
        names.add(match.group(1) or match.group(2))
    return names


def _parse_po(text: str) -> dict[tuple[str, str], str]:
    entries: dict[tuple[str, str], str] = {}
    context = ""
    msgid: str | None = None
    msgstr: str | None = None
    field: str | None = None

    def commit() -> None:
        nonlocal context, msgid, msgstr, field
        if msgid is not None and msgstr is not None:
            entries[(context, msgid)] = msgstr
        context = ""
        msgid = None
        msgstr = None
        field = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("msgctxt "):
            if msgid is not None:
                commit()
            context = _decode_po_string(line[len("msgctxt "):])
            field = "msgctxt"
        elif line.startswith("msgid "):
            if msgid is not None and msgstr is not None:
                commit()
                context = ""
            msgid = _decode_po_string(line[len("msgid "):])
            field = "msgid"
        elif line.startswith("msgstr "):
            msgstr = _decode_po_string(line[len("msgstr "):])
            field = "msgstr"
        elif line.startswith('"') and field == "msgid" and msgid is not None:
            msgid += _decode_po_string(line)
        elif line.startswith('"') and field == "msgstr" and msgstr is not None:
            msgstr += _decode_po_string(line)
        elif line.startswith('"') and field == "msgctxt":
            context += _decode_po_string(line)
    commit()
    return entries


def _decode_po_string(token: str) -> str:
    value = token.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
    return (value.replace(r"\\", "\0")
            .replace(r"\n", "\n")
            .replace(r"\t", "\t")
            .replace(r"\"", '"')
            .replace("\0", "\\"))
