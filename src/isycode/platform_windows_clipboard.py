"""Bounded native clipboard reads and Unicode input for the system clip tool."""
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
import win32api
import subprocess
import sys

MAX_BYTES = 8 * 1024 ** 2
_user = c.WinDLL('user32', use_last_error=True)
_kernel = c.WinDLL('kernel32', use_last_error=True)


def _bind(library, name, args, result):
    function = getattr(library, name)
    function.argtypes, function.restype = args, result
    return function


_open = _bind(_user, 'OpenClipboard', [w.HWND], w.BOOL)
_close = _bind(_user, 'CloseClipboard', [], w.BOOL)
_available = _bind(_user, 'IsClipboardFormatAvailable', [w.UINT], w.BOOL)
_get = _bind(_user, 'GetClipboardData', [w.UINT], w.HANDLE)
_register = _bind(_user, 'RegisterClipboardFormatW', [w.LPCWSTR], w.UINT)
_size = _bind(_kernel, 'GlobalSize', [w.HANDLE], c.c_size_t)
_lock = _bind(_kernel, 'GlobalLock', [w.HANDLE], c.c_void_p)
_unlock = _bind(_kernel, 'GlobalUnlock', [w.HANDLE], w.BOOL)


def system_clipboard_command():
    executable = Path(win32api.GetSystemDirectory()) / 'clip.exe'
    return [str(executable)] if executable.is_file() else None


def encode_text(text):
    # clip.exe accepts UTF-16LE; a BOM becomes an unwanted clipboard character.
    return text.encode('utf-16-le')


def _read_windows_clipboard():
    if not _open(None):
        raise OSError('system clipboard is busy or unavailable')
    try:
        png = _register('PNG')
        format_id, mime = (png, 'image/png') if png and _available(png) else (13, 'text/plain')
        if not _available(format_id):
            raise ValueError('unsupported clipboard type')
        handle = _get(format_id)
        if not handle:
            raise OSError('clipboard data is unavailable')
        size = _size(handle)
        maximum = MAX_BYTES * 2 + 2 if format_id == 13 else MAX_BYTES
        if not 0 < size <= maximum:
            raise ValueError('clipboard exceeds limit or is empty')
        pointer = _lock(handle)
        if not pointer:
            raise OSError('clipboard data cannot be locked')
        try:
            data = c.string_at(pointer, size)
        finally:
            _unlock(handle)
        if format_id == 13:
            if size % 2:
                raise ValueError('invalid Unicode clipboard data')
            text = data.decode('utf-16-le').removeprefix('\ufeff').split('\0', 1)[0]
            data = text.encode('utf-8')
        if not data or len(data) > MAX_BYTES:
            raise ValueError('clipboard exceeds limit or is empty')
        return mime, data
    finally:
        _close()


def _desktop_name():
    station = _bind(_user, 'GetProcessWindowStation', [], w.HANDLE)()
    desktop = _bind(_user, 'GetThreadDesktop', [w.DWORD], w.HANDLE)(win32api.GetCurrentThreadId())
    query = _bind(_user, 'GetUserObjectInformationW',
                  [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)], w.BOOL)
    names = []
    for handle in (station, desktop):
        buffer, needed = c.create_unicode_buffer(32768), w.DWORD()
        if not handle or not query(handle, 2, buffer, c.sizeof(buffer), c.byref(needed)):
            raise OSError('clipboard desktop identity unavailable')
        names.append(buffer.value)
    return '\\'.join(names)


def read_system_clipboard():
    # A delayed-render clipboard owner can block GetClipboardData. Terminate
    # only this read worker on timeout, without hanging the product's UI thread.
    startup = subprocess.STARTUPINFO()
    startup.lpDesktop = _desktop_name()
    result = subprocess.run([sys.executable, '-I', '-m', __name__],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=3, check=True,
        startupinfo=startup, close_fds=True, creationflags=subprocess.CREATE_NO_WINDOW)
    mime, separator, data = result.stdout.partition(b'\n')
    if not separator or mime not in (b'text/plain', b'image/png') or not 0 < len(data) <= MAX_BYTES:
        raise ValueError('clipboard worker returned invalid data')
    return mime.decode('ascii'), data


if __name__ == '__main__':
    mime, data = _read_windows_clipboard()
    sys.stdout.buffer.write(mime.encode('ascii') + b'\n' + data)
