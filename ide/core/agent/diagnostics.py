"""Allowlisted diagnostics without provider bodies, URLs, prompts or credentials."""
from __future__ import annotations

import json
import httpx
from core.agent.providers.base import ProviderError


def agent_failure(exc: Exception, agent=None) -> dict:
    if isinstance(exc, ProviderError):
        code, message = exc.code, exc.public_message
    elif isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        code, message = f"PROVIDER_HTTP_{status}", f"El provider respondió HTTP {status}. Revisa su disponibilidad y configuración."
    elif isinstance(exc, httpx.TimeoutException):
        code, message = "PROVIDER_TIMEOUT", "Se agotó el tiempo de espera del provider. La salida recibida es parcial."
    elif isinstance(exc, httpx.TransportError):
        code, message = "PROVIDER_TRANSPORT", "Se interrumpió la conexión con el provider. La salida recibida es parcial."
    elif isinstance(exc, json.JSONDecodeError):
        code, message = "INVALID_JSON", "Se recibió JSON inválido. La operación no pudo completarse."
    else:
        code, message = "AGENT_INTERNAL_ERROR", "El turno falló por un error interno. Consulta el diagnóstico de la conversación."
    # Frame names/locations only. Never str(exc), request/response bodies or locals.
    frames, tb = [], exc.__traceback__
    while tb is not None:
        filename = tb.tb_frame.f_code.co_filename
        relative = filename.split("/core/", 1)[-1] if "/core/" in filename else ""
        if relative and all(c.isalnum() or c in "_/.-" for c in relative):
            frames.append({"file": "core/" + relative, "line": tb.tb_lineno})
        tb = tb.tb_next
    return {"type": "agent_failed", "code": code, "message": message,
            "phase": getattr(agent, "phase", "initializing"),
            "step": getattr(agent, "turn", 0) + 1, "frames": frames[-6:]}
