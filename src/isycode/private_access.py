"""Private, non-secret ownership hints for ISyCode's Tailscale Serve route.

Saved ownership is never sufficient to remove a route: callers must also
compare the complete identity with a fresh ``serve get-config --all`` view.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from isycode.workspace_setup import state_root


@dataclass(frozen=True)
class OwnedServeRoute:
    route_id: str
    host: str
    path: str
    target: str
    created_at: str
    last_verified_status: str


@dataclass(frozen=True)
class PrivateAccessState:
    owned_routes: tuple[OwnedServeRoute, ...] = ()


class PrivateAccessStateStore:
    VERSION = 1
    OWNER = "isycode.private-tailnet"
    MAX_BYTES = 32 * 1024
    MAX_ROUTES = 8
    _ROOT_FIELDS = {"owner", "version", "adapter_version", "routes"}
    _ROUTE_FIELDS = {"route_id", "host", "path", "target", "created_at",
                     "last_verified_status"}

    def __init__(self, state_directory: Path | str | None = None):
        requested = Path(state_directory or (state_root() / "private-access")).expanduser()
        if not requested.is_absolute():
            requested = Path.cwd() / requested
        requested = Path(os.path.abspath(requested))
        self.state_directory = requested
        self._directory_fd = self._open_state_directory()
        if os.name == "posix":
            os.fchmod(self._directory_fd, 0o700)
        self.state_path = self.state_directory / "tailscale-serve.json"

    def _after_directory_open(self, path: Path, descriptor: int) -> None:
        """Test seam called after each component is pinned by descriptor."""

    def _open_state_directory(self) -> int:
        if os.name != "posix":
            # Windows does not provide dir_fd operations consistently; retain
            # the existing real-directory and reparse-point checks there.
            cursor = Path(self.state_directory.anchor)
            for part in self.state_directory.parts[1:]:
                cursor = cursor / part
                try:
                    metadata = cursor.lstat()
                except FileNotFoundError:
                    continue
                if stat.S_ISLNK(metadata.st_mode):
                    raise ValueError("Private access state path cannot traverse symlinks")
            self.state_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            if self.state_directory.is_symlink() or not self.state_directory.is_dir():
                raise ValueError("Private access state directory must be a real directory")
            return -1

        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(self.state_directory.anchor, directory_flags)
        cursor = Path(self.state_directory.anchor)
        try:
            for part in self.state_directory.parts[1:]:
                cursor = cursor / part
                try:
                    child = os.open(part, directory_flags, dir_fd=descriptor)
                except FileNotFoundError:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                    child = os.open(part, directory_flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
                self._after_directory_open(cursor, descriptor)
            return descriptor
        except OSError as exc:
            os.close(descriptor)
            raise ValueError("Private access state path must contain only real directories") from exc

    @staticmethod
    def _safe_file(info: os.stat_result) -> bool:
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            return False
        return (os.name != "posix" or
                (info.st_uid == os.getuid() and not (info.st_mode & 0o077)))

    @classmethod
    def _route_from_json(cls, value: object) -> OwnedServeRoute:
        if not isinstance(value, dict) or set(value) != cls._ROUTE_FIELDS:
            raise ValueError("Private access route fields are invalid")
        if not all(isinstance(value.get(key), str) for key in cls._ROUTE_FIELDS):
            raise ValueError("Private access route values must be strings")
        route = OwnedServeRoute(**value)
        if (not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}", route.route_id)
                or not isinstance(route.host, str) or len(route.host) > 259
                # Serve identity is Tailscale's HostPort key ("$DNS:$PORT").
                or not re.fullmatch(r"[a-zA-Z0-9.-]+(?::[1-9][0-9]{0,4})?", route.host)
                or not isinstance(route.path, str) or not route.path.startswith("/")
                or len(route.path) > 1024 or "?" in route.path or "#" in route.path
                or not isinstance(route.created_at, str)
                or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", route.created_at)
                or route.last_verified_status not in {"online", "offline", "verification_unavailable"}):
            raise ValueError("Private access route identity is malformed")
        parsed = urlsplit(route.target)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
                or parsed.port is None or not 1 <= parsed.port <= 65535
                or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
            raise ValueError("Owned Serve target must be an exact loopback URL")
        return route

    def load(self) -> PrivateAccessState:
        try:
            if os.name == "posix":
                before = os.stat(self.state_path.name, dir_fd=self._directory_fd, follow_symlinks=False)
            else:
                before = self.state_path.lstat()
        except FileNotFoundError:
            return PrivateAccessState()
        except OSError as exc:
            raise ValueError("Private access state cannot be inspected") from exc
        if not self._safe_file(before) or before.st_size > self.MAX_BYTES:
            raise ValueError("Private access state is not a bounded private regular file")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            if os.name == "posix":
                fd = os.open(self.state_path.name, flags, dir_fd=self._directory_fd)
            else:
                fd = os.open(self.state_path, flags)
            try:
                opened = os.fstat(fd)
                if (not self._safe_file(opened) or opened.st_dev != before.st_dev
                        or opened.st_ino != before.st_ino or opened.st_size > self.MAX_BYTES):
                    raise ValueError("Private access state changed during inspection")
                chunks = []
                while True:
                    chunk = os.read(fd, min(8192, self.MAX_BYTES + 1 - sum(map(len, chunks))))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    if sum(map(len, chunks)) > self.MAX_BYTES:
                        raise ValueError("Private access state exceeds its size limit")
                after = os.fstat(fd)
                if (after.st_size != opened.st_size or after.st_mtime_ns != opened.st_mtime_ns
                        or after.st_ctime_ns != opened.st_ctime_ns):
                    raise ValueError("Private access state changed while reading")
                payload = b"".join(chunks)
            finally:
                os.close(fd)
            data = json.loads(payload.decode("utf-8"))
        except ValueError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("Private access state is unreadable or malformed") from exc
        if (not isinstance(data, dict) or set(data) != self._ROOT_FIELDS
                or data.get("owner") != self.OWNER or type(data.get("version")) is not int
                or data.get("version") != self.VERSION or type(data.get("adapter_version")) is not int
                or data.get("adapter_version") != 1 or not isinstance(data.get("routes"), list)
                or len(data["routes"]) > self.MAX_ROUTES):
            raise ValueError("Private access state owner or version is invalid")
        routes = tuple(self._route_from_json(item) for item in data["routes"])
        if len({r.route_id for r in routes}) != len(routes):
            raise ValueError("Private access state contains duplicate route IDs")
        return PrivateAccessState(routes)

    def record_owned_route(self, route: OwnedServeRoute) -> None:
        route = self._route_from_json(route.__dict__)
        routes = {item.route_id: item for item in self.load().owned_routes}
        routes[route.route_id] = route
        self._write(tuple(routes.values()))

    def clear_owned_route(self, route_id: str) -> None:
        if not isinstance(route_id, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}", route_id):
            raise ValueError("Private access route ID is invalid")
        routes = tuple(item for item in self.load().owned_routes if item.route_id != route_id)
        self._write(routes)

    def _write(self, routes: tuple[OwnedServeRoute, ...]) -> None:
        if len(routes) > self.MAX_ROUTES:
            raise ValueError("Private access state contains too many routes")
        for route in routes:
            self._route_from_json(route.__dict__)
        data = {"owner": self.OWNER, "version": self.VERSION, "adapter_version": 1,
                "routes": [route.__dict__ for route in routes]}
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        if len(payload) > self.MAX_BYTES:
            raise ValueError("Private access state exceeds its size limit")
        temporary = ".private-access-" + secrets.token_hex(8) + ".tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        if os.name == "posix":
            fd = os.open(temporary, flags, 0o600, dir_fd=self._directory_fd)
        else:
            fd = os.open(self.state_directory / temporary, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if os.name == "posix":
                os.replace(temporary, self.state_path.name,
                           src_dir_fd=self._directory_fd, dst_dir_fd=self._directory_fd)
            else:
                os.replace(self.state_directory / temporary, self.state_path)
            if os.name == "posix":
                os.chmod(self.state_path.name, 0o600, dir_fd=self._directory_fd,
                         follow_symlinks=False)
        finally:
            try:
                if os.name == "posix":
                    os.unlink(temporary, dir_fd=self._directory_fd)
                else:
                    (self.state_directory / temporary).unlink()
            except FileNotFoundError:
                pass


__all__ = ["OwnedServeRoute", "PrivateAccessState", "PrivateAccessStateStore"]
