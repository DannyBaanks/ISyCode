"""POSIX clipboard tools; imported only at the composition boundary."""
import os
import shutil
import subprocess
import sys

TOOL_TIMEOUT_S = 3


def system_clipboard_command() -> list[str] | None:
    """The first available system clipboard writer for this session, or None."""
    candidates: list[list[str]] = []
    if sys.platform == "darwin":
        candidates.append(["pbcopy"])
    else:
        if os.environ.get("WAYLAND_DISPLAY"):
            candidates.append(["wl-copy"])
        if os.environ.get("DISPLAY"):
            candidates += [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
    for command in candidates:
        found = shutil.which(command[0])
        if found:
            return [found, *command[1:]]
    return None


def _bounded_clipboard_read(command: list[str], limit: int) -> bytes:
    import threading
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        timer = threading.Timer(TOOL_TIMEOUT_S, process.kill)
        timer.start()
        try:
            data = process.stdout.read(limit + 1)
            if len(data) > limit:
                process.kill()
                raise ValueError("clipboard exceeds limit")
            if process.wait(timeout=TOOL_TIMEOUT_S) != 0:
                raise ValueError("clipboard read failed")
            return data
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()


def read_system_clipboard() -> tuple[str, bytes]:
    if os.environ.get("WAYLAND_DISPLAY") and (tool := shutil.which("wl-paste")):
        types = _bounded_clipboard_read([tool, "--list-types"], 4096).decode("utf-8").splitlines()
        command = lambda mime: [tool, "--no-newline", "--type", mime]
    elif os.environ.get("DISPLAY") and (tool := shutil.which("xclip")):
        types = _bounded_clipboard_read([tool, "-selection", "clipboard", "-o", "-t", "TARGETS"], 4096).decode("utf-8").splitlines()
        command = lambda mime: [tool, "-selection", "clipboard", "-o", "-t", mime]
    else:
        raise ValueError("no Linux clipboard reader")
    mime = next((t for t in ("image/png", "image/jpeg", "image/webp", "image/gif", "text/plain;charset=utf-8", "UTF8_STRING", "text/plain") if t in types), None)
    if mime is None:
        raise ValueError("unsupported clipboard type")
    data = _bounded_clipboard_read(command(mime), 8 * 1024 * 1024)
    if not data:
        raise ValueError("empty clipboard")
    return (mime if mime.startswith("image/") else "text/plain"), data



def encode_text(text):
    return text.encode("utf-8")
