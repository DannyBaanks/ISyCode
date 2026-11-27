"""Semantic extension-to-tool router (Attachment RAG) and safe inspector for ISyCode IDE.

Supports ANY file extension pasted or attached in the chat composer:
- Stages pasted clipboard images or external files into project_state(workspace)/attachments
  so the user's Git working tree stays clean.
- Routes every extension semantically to the right native + ISyMCP Hub tool
  (e.g. images -> conditional FlowSight if the active model lacks vision;
  binaries -> REA; audio/video -> isymcp-media; docs -> office-bridge; code -> read/inspector).
- Builds a hidden system-level prompt block so the visible user bubble stays clean.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import shutil
import struct
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.ide_state import project_state
from core.runtime.base import ExecutionResult

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".ico", ".svg"}
AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus"}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}
DOCUMENT_EXTS = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".odt", ".ods", ".rtf"}
BINARY_EXTS = {".exe", ".dll", ".so", ".dylib", ".elf", ".apk", ".wasm", ".bin", ".o", ".a", ".class", ".pyc"}
DATA_EXTS = {".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".xml", ".sql", ".db", ".sqlite", ".sqlite3", ".parquet"}
ARCHIVE_EXTS = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar"}
CODE_EXTS = {
    ".py", ".zig", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".rs", ".go", ".c", ".cc", ".cpp",
    ".h", ".hpp", ".java", ".kt", ".swift", ".rb", ".php", ".lua", ".sh", ".bash", ".zsh",
    ".md", ".txt", ".rst", ".html", ".htm", ".css", ".scss", ".ini", ".cfg", ".conf", ".env", ".log", ".bolge",
}


@dataclass(frozen=True)
class AttachmentRoute:
    path: str
    name: str
    ext: str
    category: str
    mime: str
    size_bytes: int
    native_tools: tuple[str, ...]
    mcp_servers: tuple[str, ...]
    instruction: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "ext": self.ext,
            "category": self.category,
            "mime": self.mime,
            "size_bytes": self.size_bytes,
            "native_tools": list(self.native_tools),
            "mcp_servers": list(self.mcp_servers),
            "instruction": self.instruction,
        }


def classify_extension(ext: str) -> str:
    low = (ext or "").lower()
    if low in IMAGE_EXTS:
        return "image"
    if low in AUDIO_EXTS:
        return "audio"
    if low in VIDEO_EXTS:
        return "video"
    if low in DOCUMENT_EXTS:
        return "document"
    if low in BINARY_EXTS:
        return "binary"
    if low in DATA_EXTS:
        return "data"
    if low in ARCHIVE_EXTS:
        return "archive"
    if low in CODE_EXTS:
        return "code"
    return "other"


def route_attachment(path: str | Path) -> AttachmentRoute:
    """Semantic extension router: maps any file to its optimal native + ISyMCP tool route."""
    p = Path(path)
    ext = p.suffix.lower()
    cat = classify_extension(ext)
    mime = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
    try:
        size = p.stat().st_size if p.is_file() else 0
    except OSError:
        size = 0

    if cat == "image":
        return AttachmentRoute(
            path=str(p),
            name=p.name,
            ext=ext,
            category=cat,
            mime=mime,
            size_bytes=size,
            native_tools=("isycode_attachment_inspect",),
            mcp_servers=("flowsight", "isymcp", "isymcp-media"),
            instruction=(
                f"Imagen adjunta '{p.name}' ({ext}) en '{p}'. "
                "REGLA DE VISIÓN: Si tu modelo tiene visión nativa y ya puede ver la imagen directamente, IGNORA FlowSight y responde con normalidad. "
                "Si tu modelo NO tiene visión nativa, ejecuta FlowSight vía ISyMCP (server='flowsight') "
                "o isymcp/codex_view_image para inspeccionarla; usa isycode_attachment_inspect para dimensiones/metadatos."
            ),
        )
    if cat in {"audio", "video"}:
        return AttachmentRoute(
            path=str(p),
            name=p.name,
            ext=ext,
            category=cat,
            mime=mime,
            size_bytes=size,
            native_tools=("isycode_attachment_inspect",),
            mcp_servers=("isymcp-media",),
            instruction=(
                f"Archivo multimedia ({cat}, {ext}) en '{p}'. "
                "Usa isycode_attachment_inspect para metadatos o delega a ISyMCP server='isymcp-media' para transcripción/análisis."
            ),
        )
    if cat == "document":
        return AttachmentRoute(
            path=str(p),
            name=p.name,
            ext=ext,
            category=cat,
            mime=mime,
            size_bytes=size,
            native_tools=("isycode_attachment_inspect",),
            mcp_servers=("office-bridge", "isymcp-media"),
            instruction=(
                f"Documento ({ext}) en '{p}'. "
                "Usa isycode_attachment_inspect para vista rápida o delega a ISyMCP server='office-bridge' / 'isymcp-media'."
            ),
        )
    if cat == "binary":
        return AttachmentRoute(
            path=str(p),
            name=p.name,
            ext=ext,
            category=cat,
            mime=mime,
            size_bytes=size,
            native_tools=("isycode_attachment_inspect",),
            mcp_servers=("rea",),
            instruction=(
                f"Binario/artefacto ({ext}) en '{p}'. "
                "Usa isycode_attachment_inspect (cabecera/SHA-256) o delega ingeniería inversa a ISyMCP server='rea'."
            ),
        )
    if cat == "data":
        return AttachmentRoute(
            path=str(p),
            name=p.name,
            ext=ext,
            category=cat,
            mime=mime,
            size_bytes=size,
            native_tools=("isycode_attachment_inspect", "read"),
            mcp_servers=(),
            instruction=f"Archivo de datos ({ext}) en '{p}'. Usa isycode_attachment_inspect para esquema/muestra o read.",
        )
    if cat == "archive":
        return AttachmentRoute(
            path=str(p),
            name=p.name,
            ext=ext,
            category=cat,
            mime=mime,
            size_bytes=size,
            native_tools=("isycode_attachment_inspect",),
            mcp_servers=(),
            instruction=f"Archivo comprimido ({ext}) en '{p}'. Usa isycode_attachment_inspect para listar su contenido sin extraerlo.",
        )
    if cat == "code":
        return AttachmentRoute(
            path=str(p),
            name=p.name,
            ext=ext,
            category=cat,
            mime=mime,
            size_bytes=size,
            native_tools=("read", "isycode_motor", "isycode_attachment_inspect"),
            mcp_servers=(),
            instruction=f"Archivo de código/texto ({ext}) en '{p}'. Usa read o isycode_motor(motor='inspector') / isycode_attachment_inspect.",
        )
    return AttachmentRoute(
        path=str(p),
        name=p.name,
        ext=ext or "(sin extensión)",
        category="other",
        mime=mime,
        size_bytes=size,
        native_tools=("isycode_attachment_inspect",),
        mcp_servers=("isymcp",),
        instruction=f"Archivo adjunto ({ext or 'sin ext'}) en '{p}'. Usa isycode_attachment_inspect para inspeccionar cabecera/MIME/preview.",
    )


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip()) or "attachment.bin"
    return cleaned[:100]


def stage_attachment(
    workspace: Path,
    *,
    source_path: str | Path | None = None,
    raw_bytes: bytes | None = None,
    filename: str | None = None,
) -> Path:
    """Persist a pasted/attached file in project_state(workspace)/attachments (keeps repo git-clean)."""
    att_dir = project_state(workspace) / "attachments"
    att_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)

    if source_path is not None:
        src = Path(source_path).resolve()
        if not src.is_file():
            raise FileNotFoundError(f"No existe el archivo adjunto: {source_path}")
        try:
            src.relative_to(Path(workspace).resolve())
            return src  # Already inside workspace: reference directly
        except ValueError:
            pass
        dst = att_dir / f"{ts}_{_safe_filename(filename or src.name)}"
        shutil.copy2(src, dst)
        return dst

    if raw_bytes is not None:
        dst = att_dir / f"{ts}_{_safe_filename(filename or 'pasted_image.png')}"
        dst.write_bytes(raw_bytes)
        return dst

    raise ValueError("Se requiere source_path o raw_bytes para adjuntar un archivo.")


def build_hidden_attachment_prompt(attachments: list[str | Path]) -> str:
    """Build hidden system guidance for attached files (semantic extension-to-tool RAG)."""
    if not attachments:
        return ""
    routes = [route_attachment(p) for p in attachments]
    lines = [
        "\n\n[HIDDEN ATTACHMENT TOOL-ROUTER — NO REPETIR LITERALMENTE AL USUARIO]",
        "El usuario adjuntó los siguientes archivos en este turno. Usa la ruta semántica de herramienta según su extensión:",
    ]
    for idx, r in enumerate(routes, 1):
        mcp_part = f" | ISyMCP: {', '.join(r.mcp_servers)}" if r.mcp_servers else ""
        lines.append(
            f"{idx}. {r.name} (ext={r.ext}, cat={r.category}, size={r.size_bytes}B, path={r.path})\n"
            f"   Tools: {', '.join(r.native_tools)}{mcp_part}\n"
            f"   Guía: {r.instruction}"
        )
    return "\n".join(lines)


def _image_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        head = path.read_bytes()[:64]
    except OSError:
        return None
    # PNG
    if head.startswith(b"\x89PNG\r\n\x1a\n") and len(head) >= 24:
        return struct.unpack(">II", head[16:24])
    # GIF
    if head[:6] in (b"GIF87a", b"GIF89a") and len(head) >= 10:
        return struct.unpack("<HH", head[6:10])
    # BMP
    if head[:2] == b"BM" and len(head) >= 26:
        w, h = struct.unpack("<ii", head[18:26])
        return abs(w), abs(h)
    return None


def inspect_attachment(workspace: Path, raw_path: str) -> ExecutionResult:
    """Safely inspect any workspace or staged attachment file and return metadata + preview + route."""
    if not isinstance(raw_path, str) or not raw_path.strip():
        return ExecutionResult(False, stderr="PATH_REQUIRED: indica la ruta del archivo adjunto.", returncode=1, error_code="PATH_REQUIRED")
    root = Path(workspace).resolve()
    att_root = (project_state(root) / "attachments").resolve()
    cand = Path(raw_path)
    if not cand.is_absolute():
        cand = root / cand
    resolved = cand.resolve(strict=False)
    allowed = False
    for base in (root, att_root):
        try:
            resolved.relative_to(base)
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        return ExecutionResult(False, stderr="PATH_OUTSIDE_ALLOWED: el archivo debe estar en el workspace o en los adjuntos de la sesión.", returncode=1, error_code="PATH_OUTSIDE_ALLOWED")
    if not resolved.is_file():
        return ExecutionResult(False, stderr=f"FILE_NOT_FOUND: {raw_path}", returncode=1, error_code="FILE_NOT_FOUND")

    route = route_attachment(resolved)
    h = hashlib.sha256()
    with resolved.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)

    info: dict[str, Any] = {
        "route": route.to_dict(),
        "sha256": h.hexdigest(),
    }

    if route.category == "image":
        dims = _image_dimensions(resolved)
        if dims:
            info["dimensions"] = {"width": dims[0], "height": dims[1]}
    elif route.ext == ".zip":
        try:
            with zipfile.ZipFile(resolved, "r") as zf:
                names = zf.namelist()
                info["zip_entries_total"] = len(names)
                info["zip_entries_preview"] = names[:50]
        except zipfile.BadZipFile:
            info["zip_error"] = "Archivo ZIP inválido o corrupto."
    elif route.category in {"code", "data"} or route.mime.startswith("text/"):
        try:
            text = resolved.read_text(encoding="utf-8", errors="replace")
            info["lines"] = text.count("\n") + 1
            info["preview"] = text[:4000]
        except OSError:
            pass
    else:
        try:
            magic = resolved.read_bytes()[:32]
            info["magic_hex"] = magic.hex()
        except OSError:
            pass

    return ExecutionResult(True, stdout=json.dumps(info, indent=2, ensure_ascii=False))
