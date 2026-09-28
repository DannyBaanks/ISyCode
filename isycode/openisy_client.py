"""Read-only adapter for OpenISy's experimental instance HTTP API."""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from isycode.contracts import CatalogSnapshot


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep credentials on the configured origin and prevent TLS downgrade."""

    def redirect_request(self, request, fp, code, message, headers, new_url):
        old = urllib.parse.urlsplit(request.full_url)
        new = urllib.parse.urlsplit(new_url)
        if (old.hostname != new.hostname or old.port != new.port
                or (old.scheme == "https" and new.scheme != "https")):
            return None
        return super().redirect_request(request, fp, code, message, headers, new_url)


class OpenIsyClient:
    """Read status, auth metadata and skills; this adapter never connects tools."""

    def __init__(self, directory: Path, timeout: float = 2.0) -> None:
        self.directory = directory.resolve()
        self.base_url = os.environ.get("OPENISY_API_URL", "").strip().rstrip("/")
        self.timeout = timeout
        self._authorization = self._authorization_header()
        if self.base_url:
            self._validate_base_url(self.base_url)

    @staticmethod
    def _authorization_header() -> str | None:
        password = (os.environ.get("OPENISY_SERVER_PASSWORD")
                    or os.environ.get("OPENCODE_SERVER_PASSWORD"))
        if not password:
            return None
        username = (os.environ.get("OPENISY_SERVER_USERNAME")
                    or os.environ.get("OPENCODE_SERVER_USERNAME") or "opencode")
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        return f"Basic {token}"

    @staticmethod
    def _validate_base_url(base_url: str) -> None:
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("OPENISY_API_URL must be an http(s) server URL.")
        if parsed.username or parsed.password:
            raise ValueError("Put integration credentials in environment variables, not the URL.")
        if parsed.query or parsed.fragment:
            raise ValueError("OPENISY_API_URL must not contain a query or fragment.")
        host = parsed.hostname.lower()
        local_http = host == "localhost" or host == "::1" or host.startswith("127.")
        if parsed.scheme != "https" and not local_http:
            raise ValueError("Integration credentials require HTTPS unless the server is loopback.")

    def mcp_status(self) -> CatalogSnapshot:
        return self._get_catalog("mcp", kind="MCP")

    def skills(self) -> CatalogSnapshot:
        return self._get_catalog("skill", kind="skills")

    def provider_auth(self) -> CatalogSnapshot:
        """Discover OpenISy auth methods without starting an OAuth flow."""
        if not self.base_url:
            return CatalogSnapshot(False, [], "not_configured", "No additional catalog service is configured.")
        query = urllib.parse.urlencode({"directory": str(self.directory)})
        headers = {"Accept": "application/json"}
        if self._authorization:
            headers["Authorization"] = self._authorization
        request = urllib.request.Request(
            f"{self.base_url}/provider/auth?{query}", headers=headers, method="GET")
        try:
            opener = urllib.request.build_opener(_SameOriginRedirectHandler())
            with opener.open(request, timeout=self.timeout) as response:
                payload = json.loads(response.read(2_000_001).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Integration returned an invalid provider auth catalog.")
            items = []
            for provider, methods in payload.items():
                if not isinstance(provider, str) or not isinstance(methods, list):
                    continue
                labels = []
                for method in methods:
                    if not isinstance(method, dict):
                        continue
                    name = method.get("type") or method.get("name") or "auth method"
                    labels.append(_short(str(name), 48))
                items.append({"name": provider, "methods": labels})
            return CatalogSnapshot(True, sorted(items, key=lambda item: item["name"].casefold()), "ready")
        except urllib.error.HTTPError as exc:
            state = "auth_required" if exc.code == 401 else "unsupported" if exc.code == 404 else "error"
            return CatalogSnapshot(True, [], state, f"Provider auth catalog returned HTTP {exc.code}.")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return CatalogSnapshot(True, [], "disconnected", f"Could not reach the configured catalog service ({type(exc).__name__}).")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            return CatalogSnapshot(True, [], "error", f"Could not read provider auth metadata ({type(exc).__name__}).")

    def provider_catalog(self) -> CatalogSnapshot:
        """Read OpenISy's provider inventory without selecting or authenticating."""
        if not self.base_url:
            return CatalogSnapshot(False, [], "not_configured", "No additional catalog service is configured.")
        query = urllib.parse.urlencode({"directory": str(self.directory)})
        headers = {"Accept": "application/json"}
        if self._authorization:
            headers["Authorization"] = self._authorization
        request = urllib.request.Request(
            f"{self.base_url}/provider?{query}", headers=headers, method="GET")
        try:
            opener = urllib.request.build_opener(_SameOriginRedirectHandler())
            with opener.open(request, timeout=self.timeout) as response:
                raw = response.read(32_000_001)
            if len(raw) > 32_000_000:
                raise ValueError("Provider catalog exceeded the 32 MB response limit.")
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("all"), list):
                raise ValueError("Integration returned an invalid provider catalog.")
            connected = set(payload.get("connected", [])) if isinstance(payload.get("connected", []), list) else set()
            items = []
            for provider in payload["all"]:
                if not isinstance(provider, dict):
                    continue
                provider_id = provider.get("id")
                if not isinstance(provider_id, str):
                    continue
                items.append({
                    "id": provider_id,
                    "name": _short(str(provider.get("name") or provider_id), 100),
                    "connected": provider_id in connected,
                })
            return CatalogSnapshot(True, sorted(items, key=lambda item: item["name"].casefold()), "ready")
        except urllib.error.HTTPError as exc:
            state = "auth_required" if exc.code == 401 else "unsupported" if exc.code == 404 else "error"
            return CatalogSnapshot(True, [], state, f"Provider catalog returned HTTP {exc.code}.")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return CatalogSnapshot(True, [], "disconnected", f"Could not reach the configured catalog service ({type(exc).__name__}).")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            return CatalogSnapshot(True, [], "error", f"Could not read provider catalog ({type(exc).__name__}).")

    def _get_catalog(self, endpoint: str, *, kind: str) -> CatalogSnapshot:
        if not self.base_url:
            return CatalogSnapshot(False, [], "not_configured", "No additional catalog service is configured.")
        query = urllib.parse.urlencode({"directory": str(self.directory)})
        url = f"{self.base_url}/{endpoint}?{query}"
        headers = {"Accept": "application/json"}
        if self._authorization:
            headers["Authorization"] = self._authorization
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            opener = urllib.request.build_opener(_SameOriginRedirectHandler())
            with opener.open(request, timeout=self.timeout) as response:
                payload = json.loads(response.read(2_000_001).decode("utf-8"))
            if endpoint == "mcp":
                if not isinstance(payload, dict):
                    raise ValueError("Integration returned an invalid MCP status payload.")
                items = []
                for name, status in payload.items():
                    if not isinstance(name, str) or not isinstance(status, dict):
                        continue
                    status_name = status.get("status")
                    if status_name not in {"connected", "disabled", "failed", "needs_auth", "needs_client_registration"}:
                        status_name = "unknown"
                    items.append({"name": name, "status": status_name,
                                  "has_error": bool(status.get("error"))})
                return CatalogSnapshot(True, sorted(items, key=lambda item: item["name"].casefold()), "ready")
            if not isinstance(payload, list):
                raise ValueError("Integration returned an invalid skill catalog payload.")
            items = []
            for skill in payload:
                if not isinstance(skill, dict) or not isinstance(skill.get("name"), str):
                    continue
                location = skill.get("location", "")
                items.append({
                    "name": skill["name"],
                    "description": _short(skill.get("description", ""), 140),
                    "origin": _skill_origin(str(location), self.directory),
                })
            return CatalogSnapshot(True, sorted(items, key=lambda item: item["name"].casefold()), "ready")
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                return CatalogSnapshot(True, [], "auth_required", "The configured catalog requires credentials.")
            if exc.code == 404:
                return CatalogSnapshot(True, [], "unsupported", "The catalog HTTP endpoint is unavailable or disabled.")
            return CatalogSnapshot(True, [], "error", f"Catalog returned HTTP {exc.code} for {kind}.")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return CatalogSnapshot(True, [], "disconnected", f"Could not reach the configured catalog service ({type(exc).__name__}).")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            return CatalogSnapshot(True, [], "error", f"Could not read {kind} response ({type(exc).__name__}).")


def _short(value: Any, limit: int = 180) -> str:
    if not isinstance(value, str):
        return ""
    value = " ".join(value.split())
    return value if len(value) <= limit else value[:limit - 1] + "…"


def _skill_origin(location: str, directory: Path) -> str:
    if not location:
        return "connected catalog"
    try:
        Path(location).resolve().relative_to(directory)
        return "project"
    except (OSError, ValueError):
        return "user / global"
