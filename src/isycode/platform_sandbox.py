"""Composition boundary for the shared command execution owner."""
import os


def _compose():
    if os.name == 'nt':
        from isycode.platform_windows_sandbox import WindowsSandbox
        return WindowsSandbox()
    if os.name == 'posix':
        from isycode.platform_posix_sandbox import PosixSandbox
        return PosixSandbox()
    raise RuntimeError('unsupported command sandbox platform')


sandbox_backend = _compose()
