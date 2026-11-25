"""FlowSight bridge for text-only models when images are attached in ISyCode.

When the active model does not accept native image payloads, ISyCode stages the
pasted image(s) into a session-private 0700/0600 temp file and attaches a
compact text-only instruction telling the model to:
  1. Inspect the image with FlowSight (MCP `flowsight` or CLI),
  2. Explain what it observed separating DEMONSTRATED vs INFERRED facts,
  3. Confirm accuracy with the user via `ask_user`, and
  4. If the user reports a FlowSight error, log it to this PC's private local
     failure corpus via `flowsight_log_failure` (outside any git repository).

This module never bypasses ISySentinel, never spawns subprocesses implicitly,
and never writes image bytes into the workspace or action journal.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterable


def _default_flowsight_cli(flowsight_cli_dir: Path | None = None) -> str:
    if flowsight_cli_dir is not None:
        return str(flowsight_cli_dir / "flowsight_screen.py")
    env_dir = os.environ.get("FLOWSIGHT_DIR", "").strip()
    if env_dir:
        return str(Path(env_dir).expanduser() / "flowsight_screen.py")
    return "flowsight_screen.py"


def flowsight_mcp_running(mcp_owner: object | None) -> bool:
    """Return True if a local MCP session named 'flowsight' is currently alive."""
    sessions = getattr(mcp_owner, "sessions", None)
    if not isinstance(sessions, dict):
        return False
    sess = sessions.get("flowsight")
    if sess is None:
        return False
    proc = getattr(sess, "process", None)
    return proc is not None and getattr(proc, "returncode", None) is None


def build_blind_image_guidance(
    staged_images: Iterable[dict[str, object]],
    *,
    mcp_running: bool = False,
    mcp_configured: bool = False,
    flowsight_cli_dir: Path | None = None,
) -> str:
    """Build a bounded, plain-text perception & user-confirmation prompt for blind models."""
    items = list(staged_images)
    if not items:
        return ""

    cli_script = _default_flowsight_cli(flowsight_cli_dir)
    lines = [
        "[FLOWSIGHT BLIND-VISION FALLBACK]",
        "Tu modelo activo no tiene visión nativa para la(s) imagen(es) adjunta(s).",
        "Imagen(es) disponible(s) solo en esta sesión local (fuera del repositorio git):",
    ]
    for item in items:
        label = str(item.get("label") or "[IMAGE]")
        path = str(item.get("path") or "")
        mime = str(item.get("mime") or "image/png")
        size = int(item.get("size_bytes") or 0)
        sha = str(item.get("sha256") or "")[:12]
        lines.append(f"  - {label}: path={path} mime={mime} bytes={size} sha256={sha}")

    if mcp_running:
        lines.append(
            "1. Inspecciona la imagen con el servidor MCP FlowSight ya activo: usa "
            "`mcp__flowsight__flowsight_screen_run` (por ejemplo `vf=\"theme,layout,controls,text_bands,ocr,ui_map=48:20\"`), "
            "`mcp__flowsight__flowsight_screen_query`, `mcp__flowsight__flowsight_map_blocks` "
            "(o `crop=x:y:w:h,vlm_probe=...` solo si el usuario habilitó `vlm_probe`)."
        )
    elif mcp_configured:
        lines.append(
            "1. El servidor MCP `flowsight` está configurado en `~/.config/isycode/mcp.json` pero no está iniciado: "
            "indica al usuario que puede iniciarlo desde el panel MCP de ISyCode (o, si aprueba un comando, "
            f"usar `python3 \"{cli_script}\" -i \"<path>\" -vf \"theme,layout,controls,text_bands,ocr,ui_map=48:20\"`)."
        )
    else:
        lines.append(
            "1. Intenta inspeccionar la imagen con FlowSight (MCP `flowsight` o CLI "
            f"`python3 \"{cli_script}\" -i \"<path>\" -vf \"theme,layout,controls,text_bands,ocr,ui_map=48:20\"`) "
            "si cuentas con la herramienta o aprobación del usuario."
        )

    lines.append(
        "2. Explícale al usuario qué viste separando explícitamente hechos DEMONSTRATED "
        "(geometría, colores, OCR observado) de hipótesis INFERRED, y llama a la herramienta `ask_user` "
        "para confirmar si tu lectura es correcta o qué falló."
    )
    lines.append(
        "3. Si el usuario confirma que FlowSight falló (OCR incorrecto, control no detectado, layout o diff erróneo), "
        "registra el error en el corpus privado local de ESTA PC (nunca en git) usando "
        "`mcp__flowsight__flowsight_log_failure` (o `flowsight_corpus.py log`) con la corrección del usuario."
    )
    return "\n".join(lines)


def image_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
