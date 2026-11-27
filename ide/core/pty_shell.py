"""Host PTY shell wrapper (pure stdlib, Linux/macOS).

This is the OPERATOR'S terminal: a real pseudo-terminal on the host so that
interactive programs (git, pytest, editors, coloured prompts) behave exactly
as they do in a desktop terminal. It is explicitly NOT the IsyVM sandbox and
the Agent NEVER receives it as a tool.

Design notes
------------
* ``subprocess.Popen(..., start_new_session=True)`` with the PTY *slave* as
  stdin/stdout/stderr makes the child a session leader with a controlling
  tty (``setsid`` + ``TIOCSCTTY`` semantics) — required by ``tty``,
  ``stty``, password prompts and full-screen programs.
* The *master* fd is kept non-blocking so the GUI can poll it from a
  ``QSocketNotifier`` without ever blocking the Qt event loop.
* Interactive shells ignore ``SIGTERM`` by POSIX convention, so
  :meth:`PtyShell.terminate` sends ``SIGHUP`` to the whole process group —
  exactly what a terminal emulator does when its window closes. Only
  :meth:`PtyShell.kill` escalates to ``SIGKILL``.
* Reading the master after the child exits first drains buffered output and
  then raises ``EIO``; we surface that as ``read() -> None`` (EOF).

Everything here is stdlib only and safe to import on Windows; spawning
raises :class:`PtyShellError` there instead of at import time.
"""

from __future__ import annotations

import errno
import os
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path

try:  # POSIX-only modules; import-time tolerance keeps headless CI on any OS.
    import fcntl
    import termios
    import pty
except ImportError:  # pragma: no cover - Windows / unusual platforms
    fcntl = None  # type: ignore[assignment]
    termios = None  # type: ignore[assignment]
    pty = None  # type: ignore[assignment]

__all__ = ["PtyShell", "PtyShellError", "is_supported", "default_shell"]

_IS_POSIX = os.name == "posix" and pty is not None and fcntl is not None and termios is not None

#: Bound on a single ``os.read`` so one chatty command cannot stall the loop.
READ_CHUNK = 65536


class PtyShellError(RuntimeError):
    """Raised when a PTY cannot be allocated or the shell cannot be spawned."""


def is_supported() -> bool:
    """True when this process can allocate a PTY (Linux/macOS/BSD)."""
    return _IS_POSIX


def default_shell(env: dict | None = None) -> list[str]:
    """Pick the operator's login shell, preferring ``$SHELL`` then common paths."""
    env = os.environ if env is None else env
    candidates = [env.get("SHELL", ""), "/bin/bash", "/usr/bin/bash", "/bin/zsh", "/bin/sh"]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return [candidate, "-l"]
    return ["/bin/sh"]


class PtyShell:
    """A single host shell attached to a pseudo-terminal.

    Lifecycle::

        shell = PtyShell(cwd=project_dir)
        shell.start()                 # spawn the shell
        data = shell.read()           # b"..." / b"" (nothing yet) / None (EOF)
        shell.write(b"ls\\r")
        shell.resize(rows=40, cols=120)
        shell.terminate(); shell.wait(1500)   # or shell.kill() if it refuses
    """

    def __init__(self, argv: list[str] | None = None, *, cwd: str | Path | None = None,
                 env: dict[str, str] | None = None, rows: int = 24, cols: int = 80,
                 encoding: str = "utf-8"):
        if not _IS_POSIX:
            raise PtyShellError("PTY shells require a POSIX host (pty/fcntl/termios unavailable)")
        self._argv = list(argv) if argv else default_shell(env)
        self._cwd = Path(cwd) if cwd is not None else None
        self._env = dict(os.environ if env is None else env)
        # A predictable, locale-safe environment: the GUI decodes UTF-8.
        self._env.setdefault("TERM", "xterm-256color")
        self._env.setdefault("LANG", "C.UTF-8")
        self._env.setdefault("LINES", str(rows))
        self._env.setdefault("COLUMNS", str(cols))
        self._encoding = encoding
        self._rows = max(1, int(rows))
        self._cols = max(1, int(cols))
        self._master: int | None = None
        self._proc: subprocess.Popen | None = None
        self._eof = False
        self._start_error: str | None = None

    # --- introspection -------------------------------------------------

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    @property
    def fd(self) -> int | None:
        """Master PTY file descriptor (for ``QSocketNotifier``); ``None`` when closed."""
        return self._master

    @property
    def cwd(self) -> Path | None:
        return self._cwd

    @property
    def encoding(self) -> str:
        return self._encoding

    @property
    def size(self) -> tuple[int, int]:
        return self._rows, self._cols

    @property
    def start_error(self) -> str | None:
        """Diagnostic message when the last ``start()`` failed."""
        return self._start_error

    def is_running(self) -> bool:
        """True while the child is alive and the PTY is still open."""
        proc = self._proc
        if proc is None or self._master is None or self._eof:
            return False
        return proc.poll() is None

    def exit_code(self) -> int | None:
        return self._proc.returncode if self._proc is not None else None

    # --- lifecycle -----------------------------------------------------

    def start(self) -> None:
        """Allocate the PTY and spawn the shell. Idempotent while running."""
        if self.is_running():
            return
        if self._master is not None:
            self._close_master()
        self._eof = False
        self._start_error = None
        cwd = str(self._cwd) if self._cwd is not None else None
        if cwd is not None and not os.path.isdir(cwd):
            self._start_error = f"working directory does not exist: {cwd}"
            raise PtyShellError(self._start_error)
        try:
            master, slave = pty.openpty()
        except OSError as exc:
            self._start_error = f"openpty failed: {exc}"
            raise PtyShellError(self._start_error) from exc
        try:
            self._apply_winsize(slave)
            self._proc = subprocess.Popen(
                self._argv,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=cwd,
                env=self._env,
                close_fds=True,
                start_new_session=True,   # setsid(): new session + controlling tty
            )
        except OSError as exc:
            self._start_error = f"failed to spawn {self._argv[0]}: {exc}"
            self._proc = None
            for fd in (slave, master):
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise PtyShellError(self._start_error) from exc
        finally:
            # The parent must not keep the slave open: EOF/SIGHUP detection relies on it.
            try:
                os.close(slave)
            except OSError:
                pass
        self._master = master
        os.set_blocking(master, False)

    def _apply_winsize(self, fd: int) -> None:
        try:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", self._rows, self._cols, 0, 0))
        except OSError:
            pass

    # --- I/O -----------------------------------------------------------

    def read(self) -> bytes | None:
        """Drain available output.

        Returns raw bytes (possibly empty when nothing is pending) or ``None``
        once the child has exited and the PTY reached EOF. Never blocks.
        """
        fd = self._master
        if fd is None or self._eof:
            return None
        chunks: list[bytes] = []
        while True:
            try:
                chunk = os.read(fd, READ_CHUNK)
            except BlockingIOError:
                break
            except InterruptedError:
                continue
            except OSError as exc:
                # EIO is how Linux reports "slave side closed" on a PTY master.
                self._eof = True
                if exc.errno in (errno.EIO, errno.EBADF, errno.EINVAL):
                    break
                raise
            if not chunk:
                self._eof = True
                break
            chunks.append(chunk)
            if len(chunk) < READ_CHUNK:
                break
        if chunks:
            return b"".join(chunks)
        return None if self._eof else b""

    def read_text(self) -> str | None:
        """Decoded :meth:`read` (``replace`` keeps partial UTF-8 sequences harmless)."""
        data = self.read()
        if data is None:
            return None
        return data.decode(self._encoding, "replace")

    def write(self, data: bytes | str) -> int:
        """Send keystrokes to the shell. ``str`` is encoded with the shell encoding."""
        fd = self._master
        if fd is None or self._eof:
            return 0
        if isinstance(data, str):
            data = data.encode(self._encoding, "replace")
        written = 0
        while written < len(data):
            try:
                written += os.write(fd, data[written:])
            except BlockingIOError:
                break
            except InterruptedError:
                continue
            except OSError as exc:
                self._eof = True
                if exc.errno in (errno.EIO, errno.EBADF, errno.EPIPE):
                    break
                raise
        return written

    def writeline(self, line: str) -> int:
        """Send a command line terminated by ``\\r`` (what the Enter key emits on a tty)."""
        return self.write(line.rstrip("\r\n") + "\r")

    def send_interrupt(self) -> bool:
        """``Ctrl+C``: deliver ``SIGINT`` to the terminal's foreground process group."""
        fd = self._master
        if fd is None or self._eof:
            return False
        target = self._foreground_pgrp() or self._proc.pid if self._proc is not None else None
        if target is None:
            return False
        try:
            if os.getpgid(target) == target:
                os.killpg(target, signal.SIGINT)
            else:
                os.kill(target, signal.SIGINT)
        except (ProcessLookupError, PermissionError, OSError):
            return False
        return True

    def _foreground_pgrp(self) -> int | None:
        if self._master is None:
            return None
        try:
            packed = fcntl.ioctl(self._master, termios.TIOCGPGRP, b"\x00" * 4)
            value = struct.unpack("i", packed)[0]
            return value or None
        except (OSError, struct.error):
            return None

    # --- resize --------------------------------------------------------

    def resize(self, rows: int, cols: int) -> None:
        """Update the tty size (``TIOCSWINSZ``) and notify the child with ``SIGWINCH``."""
        self._rows, self._cols = max(1, int(rows)), max(1, int(cols))
        fd = self._master
        if fd is None:
            return
        try:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", self._rows, self._cols, 0, 0))
        except OSError:
            return
        target = self._foreground_pgrp()
        if target is None and self._proc is not None:
            target = self._proc.pid
        if target is not None:
            try:
                os.kill(target, signal.SIGWINCH)
            except (ProcessLookupError, PermissionError, OSError):
                pass

    # --- shutdown ------------------------------------------------------

    def terminate(self) -> bool:
        """Hang up the terminal (``SIGHUP`` to the process group). True if signalled."""
        return self._signal_group(signal.SIGHUP)

    def kill(self) -> bool:
        """Forcefully kill the process group (``SIGKILL``). True if signalled."""
        return self._signal_group(signal.SIGKILL)

    def _signal_group(self, signum: int) -> bool:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return False
        try:
            os.killpg(os.getpgid(proc.pid), signum)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.send_signal(signum)
                return True
            except (ProcessLookupError, OSError):
                return False

    def wait(self, timeout: float | None = 1.5) -> int | None:
        """Reap the child. Returns its exit status or ``None`` if still running."""
        proc = self._proc
        if proc is None:
            return None
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def close(self, *, timeout: float = 1.0) -> int | None:
        """Terminate, wait up to ``timeout``, then kill if needed. Closes the master fd."""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            self.terminate()
            code = self.wait(timeout)
            if code is None:
                self.kill()
                code = self.wait(max(timeout, 0.5))
        else:
            code = proc.returncode if proc is not None else None
        self._close_master()
        return code

    def _close_master(self) -> None:
        fd = self._master
        self._master = None
        self._eof = True
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    # --- context manager / repr ----------------------------------------

    def __enter__(self) -> "PtyShell":
        self.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - best effort
        try:
            if self._proc is not None and self._proc.poll() is None:
                self.kill()
                self.wait(0.2)
            self._close_master()
        except Exception:
            pass

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        state = "running" if self.is_running() else "stopped"
        return f"<PtyShell pid={self.pid} {state} {self._rows}x{self._cols} cwd={self._cwd}>"


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    with PtyShell(cwd=os.getcwd()) as shell:
        shell.writeline("tty; printf '\\033[31mred\\033[0m\\n'; stty size")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            data = shell.read()
            if data:
                sys.stdout.write(data.decode("utf-8", "replace"))
            elif data is None:
                break
            else:
                time.sleep(0.05)
        code = shell.close()
    print("\nexit:", code)
