"""Win32 LPAC launcher. A suspended child must enter its Job before it runs."""
from __future__ import annotations

import ctypes as c
from ctypes import wintypes as w
import subprocess
import re
from pathlib import Path

import pywintypes
import win32api
import win32con
import win32event
import win32file
import win32job
import win32pipe

from isycode.platform_windows_sandbox_registry import restrict_profile_registry


class STARTUPINFO(c.Structure):
    _fields_ = [('cb', w.DWORD), ('lpReserved', w.LPWSTR), ('lpDesktop', w.LPWSTR),
        ('lpTitle', w.LPWSTR), ('dwX', w.DWORD), ('dwY', w.DWORD),
        ('dwXSize', w.DWORD), ('dwYSize', w.DWORD), ('dwXCountChars', w.DWORD),
        ('dwYCountChars', w.DWORD), ('dwFillAttribute', w.DWORD), ('dwFlags', w.DWORD),
        ('wShowWindow', w.WORD), ('cbReserved2', w.WORD), ('lpReserved2', c.c_void_p),
        ('hStdInput', w.HANDLE), ('hStdOutput', w.HANDLE), ('hStdError', w.HANDLE)]


class STARTUPINFOEX(c.Structure):
    _fields_ = [('StartupInfo', STARTUPINFO), ('lpAttributeList', c.c_void_p)]


class PROCESSINFO(c.Structure):
    _fields_ = [('hProcess', w.HANDLE), ('hThread', w.HANDLE),
                ('dwProcessId', w.DWORD), ('dwThreadId', w.DWORD)]


class SECURITYCAPABILITIES(c.Structure):
    _fields_ = [('AppContainerSid', c.c_void_p), ('Capabilities', c.c_void_p),
                ('CapabilityCount', w.DWORD), ('Reserved', w.DWORD)]


class SIDANDATTRIBUTES(c.Structure):
    _fields_ = [('Sid', c.c_void_p), ('Attributes', w.DWORD)]


kernel = c.WinDLL('kernel32', use_last_error=True)


def _bind(name, args, result=w.BOOL):
    fn = getattr(kernel, name)
    fn.argtypes, fn.restype = args, result
    return fn


_initialize = _bind('InitializeProcThreadAttributeList',
    [c.c_void_p, w.DWORD, w.DWORD, c.POINTER(c.c_size_t)])
_update = _bind('UpdateProcThreadAttribute', [c.c_void_p, w.DWORD, c.c_size_t,
    c.c_void_p, c.c_size_t, c.c_void_p, c.c_void_p])
_delete = _bind('DeleteProcThreadAttributeList', [c.c_void_p], None)
_create = _bind('CreateProcessW', [w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p,
    w.BOOL, w.DWORD, c.c_void_p, w.LPCWSTR, c.POINTER(STARTUPINFOEX), c.POINTER(PROCESSINFO)])
_resume = _bind('ResumeThread', [w.HANDLE], w.DWORD)
_image_name = _bind('QueryFullProcessImageNameW',
    [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)])


def _check(value):
    if not value:
        raise c.WinError(c.get_last_error())


def mapped_image(process):
    buffer = c.create_unicode_buffer(32768)
    size = w.DWORD(len(buffer))
    _check(_image_name(int(process), 1, buffer, c.byref(size)))  # PROCESS_NAME_NATIVE
    if not 0 < size.value < len(buffer):
        raise OSError('native image path is truncated')
    return buffer.value


class LaunchImage:
    """Translate a pinned GUID file for CreateProcess, then verify its mapping."""
    def __init__(self, path, handle=None, native_path=None):
        self.path, self.handle, self.native_path = path, handle, native_path

    @classmethod
    def open(cls, executable):
        requested = str(executable)
        if not requested.casefold().startswith('\\\\?\\volume{'):
            return cls(requested)
        handle = win32file.CreateFile(requested, 0x80, win32con.FILE_SHARE_READ,
            None, win32con.OPEN_EXISTING, 0x00200000, None)  # FILE_FLAG_OPEN_REPARSE_POINT
        try:
            info = win32file.GetFileInformationByHandle(handle)
            if info[0] & (0x400 | 0x10) or info[7] != 1:
                raise OSError('launch image must be a single regular file')
            guid = win32file.GetFinalPathNameByHandle(handle, 1)
            dos = win32file.GetFinalPathNameByHandle(handle, 0)
            native = win32file.GetFinalPathNameByHandle(handle, 2)
            if (guid.casefold() != requested.casefold()
                    or not re.match(r'^\\\\\?\\[A-Za-z]:\\', dos)
                    or not native.casefold().startswith('\\device\\')):
                raise OSError('launch image has no matching local DOS alias')
            return cls(dos[4:], handle, native)
        except BaseException:
            handle.Close()
            raise

    def verify(self, process):
        if self.native_path is not None:
            actual = mapped_image(process)
            if actual.casefold() != self.native_path.casefold():
                raise OSError('suspended image mapping differs from the pinned volume image')

    def close(self):
        if self.handle is not None:
            handle, self.handle = self.handle, None
            handle.Close()


class WindowsSandboxProcess:
    def __init__(self, process, job, output, pid):
        self.process, self.job, self.output, self.pid = process, job, output, pid

    @classmethod
    def launch(cls, executable: Path, argv: tuple[str, ...], cwd: Path,
               env: dict[str, str], profile_sid: bytes, max_processes: int,
               capability_sids: tuple[bytes, ...] = ()):
        if not argv or str(executable) != argv[0] or not 1 <= max_processes <= 256:
            raise ValueError('invalid sandbox launch')
        if any('\0' in item for item in (*argv, *env.keys(), *env.values())):
            raise ValueError('NUL in sandbox launch')
        job = win32job.CreateJobObject(None, '')
        output = writer = stdin = process = thread = None
        attributes = image = None
        initialized = False
        try:
            image = LaunchImage.open(executable)
            limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
            limits['BasicLimitInformation']['LimitFlags'] = (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS)
            limits['BasicLimitInformation']['ActiveProcessLimit'] = max_processes
            win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
            sa = pywintypes.SECURITY_ATTRIBUTES()
            sa.bInheritHandle = True
            output, writer = win32pipe.CreatePipe(sa, 0)
            win32api.SetHandleInformation(output, win32con.HANDLE_FLAG_INHERIT, 0)
            stdin = win32file.CreateFile('NUL', win32con.GENERIC_READ,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE, sa, win32con.OPEN_EXISTING, 0, None)
            size = c.c_size_t()
            _initialize(None, 4, 0, c.byref(size))
            if c.get_last_error() != 122:
                raise c.WinError(c.get_last_error())
            attributes = c.create_string_buffer(size.value)
            _check(_initialize(attributes, 4, 0, c.byref(size)))
            initialized = True
            sid = c.create_string_buffer(profile_sid)
            cap_buffers = [c.create_string_buffer(value) for value in capability_sids]
            cap_array = (SIDANDATTRIBUTES * len(cap_buffers))(
                *(SIDANDATTRIBUTES(c.cast(value, c.c_void_p), 4) for value in cap_buffers))
            capabilities = SECURITYCAPABILITIES(c.cast(sid, c.c_void_p),
                c.cast(cap_array, c.c_void_p) if cap_buffers else None, len(cap_buffers), 0)
            opt_out = w.DWORD(1)
            handles = (w.HANDLE * 2)(int(writer), int(stdin))
            jobs = (w.HANDLE * 1)(int(job))
            for key, value in ((0x20009, capabilities), (0x2000F, opt_out),
                               (0x20002, handles), (0x2000D, jobs)):
                _check(_update(attributes, 0, key, c.byref(value), c.sizeof(value), None, None))
            info = STARTUPINFOEX()
            info.StartupInfo.cb = c.sizeof(info)
            info.StartupInfo.dwFlags = win32con.STARTF_USESTDHANDLES
            info.StartupInfo.hStdInput = int(stdin)
            info.StartupInfo.hStdOutput = info.StartupInfo.hStdError = int(writer)
            info.lpAttributeList = c.cast(attributes, c.c_void_p)
            pi = PROCESSINFO()
            block = c.create_unicode_buffer('\0'.join(f'{k}={v}' for k, v in sorted(env.items())) + '\0\0')
            command = c.create_unicode_buffer(subprocess.list2cmdline((image.path, *argv[1:])))
            _check(_create(image.path, command, None, None, True,
                0x80000 | 0x400 | win32con.CREATE_SUSPENDED | win32con.CREATE_NO_WINDOW,
                block, str(cwd), c.byref(info), c.byref(pi)))
            process, thread = pywintypes.HANDLE(pi.hProcess), pywintypes.HANDLE(pi.hThread)
            if not win32job.IsProcessInJob(process, job):
                raise OSError('native child was not atomically assigned to its Job')
            image.verify(process)
            restrict_profile_registry(process, profile_sid)
            if _resume(int(thread)) == 0xFFFFFFFF:
                raise c.WinError(c.get_last_error())
            result = cls(process, job, output, pi.dwProcessId)
            process = job = output = None  # ownership transferred
            return result
        except BaseException:
            if process is not None:
                win32api.TerminateProcess(process, 1)
                win32event.WaitForSingleObject(process, 10000)
            raise
        finally:
            if initialized:
                _delete(attributes)
            try:
                for handle in (thread, process, writer, stdin, output, job):
                    if handle is not None:
                        handle.Close()
            finally:
                if image is not None:
                    image.close()

    def read(self, size: int) -> bytes:
        try:
            return win32file.ReadFile(self.output, size)[1]
        except pywintypes.error as exc:
            if exc.winerror == 109:
                return b''
            raise

    def wait(self, timeout: float | None = None) -> int:
        milliseconds = win32event.INFINITE if timeout is None else max(0, int(timeout * 1000))
        if win32event.WaitForSingleObject(self.process, milliseconds) != win32event.WAIT_OBJECT_0:
            raise TimeoutError('sandbox process did not exit')
        return win32process_exit(self.process)

    def terminate_tree(self) -> None:
        if self.job is not None:
            win32job.TerminateJobObject(self.job, 1)

    def close(self) -> None:
        self.terminate_tree()
        for name in ('process', 'job', 'output'):
            handle = getattr(self, name)
            if handle is not None:
                handle.Close()
                setattr(self, name, None)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def win32process_exit(handle):
    import win32process
    return win32process.GetExitCodeProcess(handle)
