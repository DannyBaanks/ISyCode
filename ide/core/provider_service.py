"""Provider setup and diagnostics shared by Qt and the bundled TUI.

No Qt imports, credential values in reports, inference calls or invented model
capabilities. Model listing is a connection diagnostic, not a generation test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import time

import httpx

from core.agent.providers.registry import ProviderRegistry
from core.ide_state import atomic_write, state_home, state_lock


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    label: str
    protocol: str
    endpoint: str
    category: str = "API"
    auth: str = "api_key"


PRESETS = (
    ProviderPreset("openai", "OpenAI", "openai", "https://api.openai.com/v1"),
    ProviderPreset("anthropic", "Anthropic", "anthropic", "https://api.anthropic.com/v1"),
    ProviderPreset("google", "Google Gemini", "google", "https://generativelanguage.googleapis.com/v1beta"),
    ProviderPreset("compatible", "Compatible con OpenAI", "openai-compatible", ""),
    ProviderPreset("nvidia", "NVIDIA NIM", "nvidia", "https://integrate.api.nvidia.com/v1"),
    ProviderPreset("openrouter", "OpenRouter", "openai-compatible", "https://openrouter.ai/api/v1"),
    ProviderPreset("groq", "Groq", "openai-compatible", "https://api.groq.com/openai/v1"),
    ProviderPreset("deepseek", "DeepSeek", "openai-compatible", "https://api.deepseek.com/v1"),
    ProviderPreset("mistral", "Mistral", "openai-compatible", "https://api.mistral.ai/v1"),
    ProviderPreset("ollama", "Ollama", "ollama", "http://localhost:11434", "Local", "none"),
    ProviderPreset("lmstudio", "LM Studio", "openai-compatible", "http://localhost:1234/v1", "Local", "none"),
    ProviderPreset("isyco-web", "ISyCo Web", "openai-compatible", "http://127.0.0.1:8792/v1", "Local", "none"),
)


@dataclass(frozen=True)
class ConnectionReport:
    provider: str
    state: str
    message: str
    models: tuple[str, ...] = field(default_factory=tuple)
    listing_only: bool = True


@dataclass(frozen=True)
class PingResult:
    provider: str
    model: str
    ok: bool
    latency_ms: int
    reply: str = ""
    error: str = ""
    checked_at: str = ""


class ModelPingStore:
    """Persist last pong latency or error per (provider, model) in IDE state."""

    def __init__(self):
        self.path = state_home() / "model_pings.json"

    @staticmethod
    def _key(provider: str, model: str) -> str:
        return f"{provider}::{model}"

    def load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, provider: str, model: str) -> dict | None:
        if not provider or not model:
            return None
        entry = self.load().get(self._key(provider, model))
        return entry if isinstance(entry, dict) else None

    def record(self, result: PingResult) -> dict:
        entry = {
            "provider": result.provider,
            "model": result.model,
            "ok": bool(result.ok),
            "latency_ms": int(result.latency_ms),
            "reply": (result.reply or "")[:120],
            "error": (result.error or "")[:300],
            "checked_at": result.checked_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        with state_lock(self.path.with_suffix(".lock")):
            data = self.load()
            data[self._key(result.provider, result.model)] = entry
            # Keep bounded to last 200 entries
            if len(data) > 200:
                keys = list(data.keys())[-200:]
                data = {k: data[k] for k in keys}
            atomic_write(self.path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return entry


class ProviderService:
    def __init__(self, registry: ProviderRegistry):
        self.registry = registry

    def catalog(self) -> tuple[ProviderPreset, ...]:
        return PRESETS

    def configured(self) -> dict:
        return self.registry.list()

    def save(self, name: str, protocol: str, model: str, **values) -> str:
        return self.registry.add(name, protocol, model, **values)

    async def inspect(self, name: str) -> ConnectionReport:
        config = self.registry.get_config(name)
        return await self.inspect_config(config)

    async def inspect_config(self, config, key: str | None = None) -> ConnectionReport:
        """Inspect an unsaved draft without persisting its credential or model."""
        name = config.name
        if config.provider_type == "claude":
            return ConnectionReport(name, "unavailable", "Selecciona Claude en Suscripciones; el transporte legado está deshabilitado.")
        if config.auth == "subscription":
            from core.subscriptions import SubscriptionService
            try:
                report = await SubscriptionService().inspect(config.provider_type)
                return ConnectionReport(name, report["state"], "Sesión del conector comprobada; generación aún sin verificar.", tuple(report["models"]))
            except (ValueError, OSError):
                return ConnectionReport(name, "connector_error", "Revisa el CLI y el perfil privado en Suscripciones.")
        key = key or self.registry.secret_broker.get(name)
        if config.auth == "api_key" and not key:
            return ConnectionReport(name, "credentials_required", "Falta una clave API. Configurar no equivale a conectar.")
        headers = {"Accept": "application/json"}
        if config.provider_type == "anthropic":
            headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
        elif config.provider_type == "google":
            headers["x-goog-api-key"] = key
        elif key and config.auth != "none":
            headers["Authorization"] = f"Bearer {key}"
        endpoint = config.endpoint
        # Compatibility with legacy configs containing full inference URLs.
        for suffix in ("/chat/completions", "/messages", "/api/chat"):
            if endpoint.endswith(suffix):
                endpoint = endpoint[:-len(suffix)]
                break
        url = endpoint + ("/api/tags" if config.provider_type == "ollama" else "/models")
        try:
            # No redirects: a configured endpoint cannot forward credentials elsewhere.
            async with httpx.AsyncClient(timeout=config.timeout, follow_redirects=False) as client:
                async with client.stream("GET", url, headers=headers) as response:
                    if response.status_code in {401, 403}:
                        return ConnectionReport(name, "auth_error", "El endpoint rechazó las credenciales o los permisos.")
                    if response.status_code in {404, 405}:
                        return ConnectionReport(name, "unsupported_listing", "Este endpoint no ofrece catálogo. Puedes introducir un modelo manualmente.")
                    if response.status_code == 429:
                        return ConnectionReport(name, "rate_limited", "El endpoint ha limitado las consultas. Inténtalo más tarde.")
                    if response.status_code >= 300:
                        return ConnectionReport(name, "http_error", f"No se pudo consultar el catálogo (HTTP {response.status_code}).")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 2_000_000:
                            return ConnectionReport(name, "invalid_response", "El catálogo supera el límite de tamaño.")
                    import json
                    data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("Invalid response")
            items = data.get("models" if config.provider_type in {"ollama", "google"} else "data", [])
            if not isinstance(items, list):
                raise ValueError("Invalid model list")
            ids = set()
            for item in items[:1000]:
                if not isinstance(item, dict):
                    continue
                model = item.get("name") if config.provider_type in {"ollama", "google"} else item.get("id")
                if config.provider_type == "google" and isinstance(model, str):
                    if "generateContent" not in item.get("supportedGenerationMethods", []):
                        continue
                    model = model.removeprefix("models/")
                if isinstance(model, str) and 0 < len(model) <= 256 and all(ord(c) >= 32 for c in model) and not (key and key in model):
                    ids.add(model)
            return ConnectionReport(name, "catalog_available", "Catálogo consultado. La generación y las herramientas aún no se han comprobado.", tuple(sorted(ids)))
        except httpx.TimeoutException:
            return ConnectionReport(name, "timeout", "Se agotó el tiempo de conexión. Revisa el endpoint y el servicio.")
        except httpx.RequestError:
            return ConnectionReport(name, "network_error", "No se pudo conectar. Revisa el endpoint, la red o el servidor local.")
        except (ValueError, TypeError):
            return ConnectionReport(name, "invalid_response", "El endpoint no devolvió un catálogo válido.")

    async def ping_model(self, name: str, model: str, *, store: ModelPingStore | None = None) -> PingResult:
        """Send a minimal 'pong' probe to verify live model response and persist latency or error."""
        checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        t0 = time.perf_counter()
        provider = None
        ping_store = store or ModelPingStore()
        try:
            provider = self.registry.get(name, model or None)
            reply_chunks: list[str] = []
            async for event in provider.stream_completion(
                [{"role": "user", "content": "Reply with exactly one word: pong"}],
                tools=None,
            ):
                if event.kind == "text" and event.text:
                    reply_chunks.append(event.text)
                elif event.kind == "completed" and event.response is not None:
                    if not reply_chunks and event.response.content:
                        reply_chunks.append(event.response.content)
            elapsed_ms = max(1, int((time.perf_counter() - t0) * 1000))
            reply = "".join(reply_chunks).strip()
            result = PingResult(
                provider=name,
                model=model,
                ok=True,
                latency_ms=elapsed_ms,
                reply=reply[:120] or "pong",
                error="",
                checked_at=checked_at,
            )
        except Exception as exc:
            elapsed_ms = max(1, int((time.perf_counter() - t0) * 1000))
            err_text = str(exc).strip() or type(exc).__name__
            result = PingResult(
                provider=name,
                model=model,
                ok=False,
                latency_ms=elapsed_ms,
                reply="",
                error=err_text[:300],
                checked_at=checked_at,
            )
        finally:
            if provider is not None:
                try:
                    await provider.close()
                except Exception:
                    pass
        try:
            ping_store.record(result)
        except OSError:
            pass
        return result
