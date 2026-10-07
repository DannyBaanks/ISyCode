from __future__ import annotations

import json
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
from pathlib import Path
from typing import Any

from isycode.harness_graph import HarnessSetting, SkippedFile, display_value


def skipped(harness_id: str, relative_path: str, reason: str) -> SkippedFile:
    return SkippedFile(harness_id, relative_path, reason)  # type: ignore[arg-type]


def row(
    harness_id: str,
    relative_path: str,
    pointer: str,
    value: object,
    semantic_id: str | None,
    *,
    edge: str = "same",
    shown: str | None = None,
    provider_id: str | None = None,
    model_id: str | None = None,
    counts_toward_n: bool = True,
) -> HarnessSetting:
    return HarnessSetting(
        harness_id=harness_id,
        relative_path=relative_path,
        pointer=pointer,
        value_type=type(value).__name__,
        semantic_id=semantic_id,
        edge=edge,  # type: ignore[arg-type]
        display_value=display_value(value) if shown is None else shown,
        provider_id=provider_id,
        model_id=model_id,
        counts_toward_n=counts_toward_n,
    )


def safe_file(root: Path, *parts: str) -> Path | None:
    root = Path(root)
    candidate = root.joinpath(*parts)
    try:
        if root.is_symlink() or candidate.is_symlink() or not candidate.is_file():
            return None
        resolved_root = root.resolve(strict=True)
        relative = candidate.relative_to(root)
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return None
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError):
        return None
    return candidate


def load_toml(root: Path, relative_path: str) -> dict[str, Any]:
    path = safe_file(root, *Path(relative_path).parts)
    if path is None:
        return {}
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_json(root: Path, relative_path: str) -> dict[str, Any]:
    path = safe_file(root, *Path(relative_path).parts)
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def strip_json_comments(text: str) -> str:
    out: list[str] = []
    i = 0
    in_string = False
    escaped = False
    while i < len(text):
        char = text[i]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            i += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            i += 1
            continue
        if text.startswith("//", i):
            newline = text.find("\n", i + 2)
            if newline < 0:
                break
            out.append("\n")
            i = newline + 1
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                break
            out.append(" " * (end + 2 - i))
            i = end + 2
            continue
        out.append(char)
        i += 1
    return "".join(out)


def load_jsonc(root: Path, relative_path: str) -> dict[str, Any]:
    path = safe_file(root, *Path(relative_path).parts)
    if path is None:
        return {}
    try:
        data = json.loads(strip_json_comments(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _yaml_scalar(text: str) -> object:
    value = text.strip()
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "Null", "NULL", "~"}:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def load_simple_yaml(root: Path, relative_path: str) -> dict[str, Any]:
    """Parse the tiny mapping/list subset used by reviewed harness fixtures."""
    path = safe_file(root, *Path(relative_path).parts)
    if path is None:
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return {}

    result: dict[str, Any] = {}
    current_map: dict[str, Any] | None = None
    current_list: list[Any] | None = None
    current_indent = -1
    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        text = raw.strip()
        if indent == 0:
            current_map = None
            current_list = None
            current_indent = -1
            if ":" not in text:
                continue
            key, value = text.split(":", 1)
            key = key.strip()
            if value.strip():
                result[key] = _yaml_scalar(value)
            else:
                result[key] = {}
                current_map = result[key]
                current_indent = indent
            continue
        if current_map is None:
            continue
        if text.startswith("- "):
            if current_list is None:
                # Convert the currently empty map container into a list by locating it.
                for key, value in result.items():
                    if value is current_map:
                        result[key] = []
                        current_list = result[key]
                        current_map = None
                        break
            if current_list is not None:
                current_list.append(_yaml_scalar(text[2:]))
            continue
        if ":" in text and indent > current_indent:
            key, value = text.split(":", 1)
            current_map[key.strip()] = _yaml_scalar(value)
    return result
