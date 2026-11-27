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

import asyncio
import hashlib
import json
import mimetypes
import os
import re
import shutil
import struct
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.ide_state import atomic_write, project_state, state_lock
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


def issue_attachment_token(workspace: Path, path: str | Path) -> str:
    """Issue and persist a reusable per-attachment token (`att_<hex>`) for FlowSight / image tools."""
    root = Path(workspace).resolve()
    resolved = str(Path(path).resolve())
    tok_path = project_state(root) / "attachments" / "tokens.json"
    tok_path.parent.mkdir(parents=True, exist_ok=True)
    with state_lock(tok_path.with_suffix(".lock")):
        data: dict[str, str] = {}
        if tok_path.is_file():
            try:
                loaded = json.loads(tok_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = {str(k): str(v) for k, v in loaded.items()}
            except (OSError, ValueError):
                data = {}
        for existing_tok, existing_path in data.items():
            if existing_path == resolved:
                return existing_tok
        token = f"att_{uuid.uuid4().hex[:12]}"
        data[token] = resolved
        if len(data) > 200:
            keys = list(data.keys())[-200:]
            data = {k: data[k] for k in keys}
        atomic_write(tok_path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return token


def resolve_attachment_token(workspace: Path, token: str) -> Path | None:
    """Resolve an `att_<hex>` token back to its staged/workspace file path."""
    if not token or not isinstance(token, str):
        return None
    tok_path = project_state(Path(workspace).resolve()) / "attachments" / "tokens.json"
    if not tok_path.is_file():
        return None
    try:
        data = json.loads(tok_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    raw = data.get(token.strip()) if isinstance(data, dict) else None
    if not isinstance(raw, str):
        return None
    p = Path(raw).resolve()
    return p if p.is_file() else None


def build_hidden_attachment_prompt(attachments: list[str | Path], workspace: Path | None = None) -> str:
    """Build hidden system guidance for attached files (semantic extension-to-tool RAG)."""
    if not attachments:
        return ""
    routes = [route_attachment(p) for p in attachments]
    lines = [
        "\n\n[HIDDEN ATTACHMENT TOOL-ROUTER — NO REPETIR LITERALMENTE AL USUARIO]",
        "El usuario adjuntó los siguientes archivos en este turno. Usa la ruta semántica de herramienta según su extensión:",
    ]
    for idx, r in enumerate(routes, 1):
        tok_part = ""
        if workspace is not None and r.category == "image":
            try:
                tok = issue_attachment_token(workspace, r.path)
                tok_part = f", token={tok}"
                extra_guide = (
                    f"Imagen adjunta '{r.name}' ({r.ext}) · token='{tok}' · path='{r.path}'. "
                    "REGLA DE VISIÓN: Si tu modelo tiene visión nativa y ya ve la imagen, IGNORA isycode_see_image y responde directo. "
                    f"Si NO tienes visión nativa, llama EN UN SOLO PASO: isycode_see_image(token='{tok}') — "
                    "devuelve el texto OCR real, paneles, botones y un boceto de la imagen en 1 sola llamada. "
                    "Con ese resultado responde directamente; NO uses isycode_mcp_discover/describe/execute ni isycode_motor para la imagen."
                )
            except OSError:
                extra_guide = r.instruction
        else:
            extra_guide = r.instruction
        mcp_part = f" | ISyMCP: {', '.join(r.mcp_servers)}" if r.mcp_servers else ""
        lines.append(
            f"{idx}. {r.name} (ext={r.ext}, cat={r.category}, size={r.size_bytes}B{tok_part}, path={r.path})\n"
            f"   Tools: {', '.join(r.native_tools)}{mcp_part}\n"
            f"   Guía: {extra_guide}"
        )
    return "\n".join(lines)


SCREEN_VF = "theme,layout,controls,text_bands,ocr,ui_map=64:24"
FLOWSIGHT_TIMEOUT_S = 150.0
_CROP_RE = re.compile(r"^\d{1,5}:\d{1,5}:\d{1,5}:\d{1,5}$")
_SESSION_RE = re.compile(r'session(?:_id)?"?\s*[:=]\s*"?([A-Za-z0-9_-]{6,64})')


def _flowsight_cache_path(root: Path, image: Path, key: str) -> Path:
    digest = hashlib.sha256(image.read_bytes()).hexdigest()[:20]
    k = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
    return project_state(root) / "attachments" / "flowsight_cache" / f"{digest}_{k}.txt"


async def see_image_with_flowsight(
    workspace: Path,
    *,
    token: str = "",
    path: str = "",
    split: str = "quarters",
    crop: str = "",
    detail: str = "screen",
) -> ExecutionResult:
    """One-call FlowSight vision for non-vision models.

    detail="screen" (default): flowsight_screen_run = OCR text + panels + controls + wireframe.
    detail="full": also map_blocks -> get_block x N -> stitch_blocks (structural color/edge maps).
    crop="x:y:w:h": zoom into a region with exact global coordinates.
    Results are cached per (image sha, options), so repeated calls are instant.
    """
    root = Path(workspace).resolve()
    resolved: Path | None = None
    if token.strip():
        resolved = resolve_attachment_token(root, token.strip())
        if resolved is None:
            return ExecutionResult(False, stderr=f"INVALID_ATTACHMENT_TOKEN: token '{token}' no encontrado.", returncode=1, error_code="INVALID_ATTACHMENT_TOKEN")
    elif path.strip():
        att_root = (project_state(root) / "attachments").resolve()
        cand = Path(path.strip())
        if not cand.is_absolute():
            cand = root / cand
        cand = cand.resolve(strict=False)
        for base in (root, att_root):
            try:
                cand.relative_to(base)
                resolved = cand
                break
            except ValueError:
                continue
        if resolved is None:
            return ExecutionResult(False, stderr="PATH_OUTSIDE_ALLOWED: ruta fuera del workspace/adjuntos.", returncode=1, error_code="PATH_OUTSIDE_ALLOWED")
    else:
        return ExecutionResult(False, stderr="TOKEN_OR_PATH_REQUIRED: proporciona token o path de la imagen.", returncode=1, error_code="TOKEN_OR_PATH_REQUIRED")

    if not resolved.is_file():
        return ExecutionResult(False, stderr=f"FILE_NOT_FOUND: {resolved}", returncode=1, error_code="FILE_NOT_FOUND")

    crop = crop.strip()
    if crop and not _CROP_RE.match(crop):
        return ExecutionResult(False, stderr="INVALID_CROP: usa crop='x:y:w:h' en píxeles (ej. '400:120:800:300').", returncode=1, error_code="INVALID_CROP")
    detail = detail if detail in {"screen", "full"} else "screen"
    valid_split = split if split in {"quarters", "halves_h", "halves_v"} else "quarters"
    vf = (f"crop={crop}," if crop else "") + SCREEN_VF
    tok = token.strip() or issue_attachment_token(root, resolved)

    cache_path = _flowsight_cache_path(root, resolved, f"{vf}|{detail}|{valid_split}")
    if cache_path.is_file():
        cached = cache_path.read_text(encoding="utf-8")
        return ExecutionResult(True, stdout="[FlowSight: resultado en caché, misma imagen y opciones]\n" + cached,
                               evidence={"flowsight": {"image": str(resolved), "cached": True}})

    from core.isymcp_hub_client import load_local_mcp_servers, _extract_mcp_text
    local_mcps = load_local_mcp_servers()
    fs_spec = local_mcps.get("flowsight")
    if fs_spec is None:
        default_script = Path("/home/danny/Development/ISyCo Git/FlowSight/flowsight_mcp.py")
        if default_script.is_file():
            fs_spec = {"command": ["python3", str(default_script)], "env": {"FLOWSIGHT_VLM_ENABLED": "0"}}
        else:
            return ExecutionResult(False, stderr="FLOWSIGHT_UNAVAILABLE: flowsight_mcp.py no encontrado.", returncode=1, error_code="FLOWSIGHT_UNAVAILABLE")

    env = os.environ.copy()
    env.update(fs_spec.get("env") or {})
    proc = await asyncio.create_subprocess_exec(
        *fs_spec["command"],
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=env,
        limit=8 * 1024 * 1024,
    )
    assert proc.stdin is not None and proc.stdout is not None

    next_id = 1

    async def _rpc(method: str, params: dict[str, Any]) -> dict[str, Any]:
        nonlocal next_id
        req_id = next_id
        next_id += 1
        proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}, ensure_ascii=False) + "\n").encode("utf-8"))
        await proc.stdin.drain()
        while True:
            line = await proc.stdout.readline()
            if not line:
                raise RuntimeError("FlowSight MCP cerró stdout inesperadamente.")
            text = line.decode("utf-8", "replace").strip()
            if not text:
                continue
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and msg.get("id") == req_id:
                return msg

    async def _call(tool: str, arguments: dict[str, Any]) -> str:
        resp = await _rpc("tools/call", {"name": tool, "arguments": arguments})
        if "error" in resp:
            raise RuntimeError(f"{tool} error: {resp['error']}")
        return _extract_mcp_text(resp.get("result") or {})

    async def _run_pipeline() -> str:
        init = await _rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "isycode-ide-flowsight", "version": "0.5.0"},
        })
        if "error" in init:
            raise RuntimeError(f"FlowSight init error: {init['error']}")
        proc.stdin.write((json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}) + "\n").encode("utf-8"))
        await proc.stdin.drain()

        screen = await _call("flowsight_screen_run", {"image_path": str(resolved), "vf": vf, "max_chars": 16000})

        sections = [screen.strip()]
        if detail == "full":
            mapped = await _call("flowsight_map_blocks", {
                "image_path": str(resolved), "split": valid_split, "palette_k": 12, "grid_w": 24, "grid_h": 14,
            })
            m = _SESSION_RE.search(mapped)
            session_id = m.group(1) if m else ""
            sections.append("=== BLOCKS MAP ===\n" + mapped.strip()[:3500])
            if session_id:
                block_ids = ["TL", "TR", "BL", "BR"] if valid_split == "quarters" else (["L", "R"] if valid_split == "halves_h" else ["T", "B"])
                for bid in block_ids:
                    sections.append(f"=== BLOCK {bid} ===\n" + (await _call("flowsight_get_block", {
                        "session_id": session_id, "block_id": bid, "include_edge_map": True,
                    })).strip()[:2500])
                sections.append("=== STITCH ===\n" + (await _call("flowsight_stitch_blocks", {"session_id": session_id})).strip()[:4500])
            else:
                sections.append("[BLOCKS: FlowSight no devolvió session_id; se omiten bloques]")
        return "\n\n".join(sections)

    try:
        body = await asyncio.wait_for(_run_pipeline(), timeout=FLOWSIGHT_TIMEOUT_S)
    except asyncio.TimeoutError:
        return ExecutionResult(False, stderr=f"FLOWSIGHT_TIMEOUT: el análisis excedió {int(FLOWSIGHT_TIMEOUT_S)}s. Reintenta con crop='x:y:w:h' sobre la zona de interés.", returncode=1, error_code="FLOWSIGHT_TIMEOUT")
    except Exception as exc:
        return ExecutionResult(False, stderr=f"FLOWSIGHT_ERROR: {type(exc).__name__}: {exc}", returncode=1, error_code="FLOWSIGHT_ERROR")
    finally:
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=1.5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    if body.lstrip().startswith("DENY"):
        return ExecutionResult(False, stderr=f"FLOWSIGHT_DENY: {body.strip()[:500]}", returncode=1, error_code="FLOWSIGHT_DENY")

    dims = _image_dimensions(resolved)
    dims_s = f"{dims[0]}x{dims[1]}" if dims else "?"
    report = (
        f"ISYCODE VISION (FlowSight, 1 llamada) · token={tok} · imagen={resolved.name} ({dims_s})"
        f"{' · crop=' + crop if crop else ''} · detail={detail}\n"
        "Lee así: OCR = texto real visible en la imagen; CONTROLS = botones/campos con su texto y centro click=(x,y); "
        "LAYOUT = paneles; UI WIREFRAME MAP = boceto ASCII de la distribución.\n\n"
        f"{body}\n\n"
        "[FIN DE LA VISIÓN] Esta es la percepción completa de la imagen. Responde al usuario YA con lo que ves "
        "(describe la interfaz/escena y el texto relevante en lenguaje natural). NO llames isycode_mcp_* ni otras tools "
        "de FlowSight para esta imagen. Solo si el usuario pide un detalle concreto, vuelve a llamar "
        f"isycode_see_image(token='{tok}', crop='x:y:w:h') sobre esa zona."
    )
    try:
        atomic_write(cache_path, report)
    except OSError:
        pass
    return ExecutionResult(True, stdout=report, evidence={"flowsight": {"image": str(resolved), "vf": vf, "detail": detail}})


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
