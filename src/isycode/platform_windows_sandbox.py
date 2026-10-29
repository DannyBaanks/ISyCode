"""Native CPython command backend; activation awaits adversarial acceptance."""
from __future__ import annotations
import asyncio
import hashlib
from pathlib import Path, PureWindowsPath
import sys

import pywintypes
import win32job
import win32pipe
import win32process
import win32event

from isycode.platform_windows_sandbox_process import WindowsSandboxProcess
from isycode.platform_windows_sandbox_resources import WindowsSandboxResources
from isycode.platform_windows_sandbox_volume import BoundedStorageProvider, StorageIdentity, StorageUnavailableError

NATIVE_ACCEPTED = False


class NativeOutput:
    def __init__(self, process):
        self.process = process

    async def read(self, size):
        while True:
            try:
                _, available, _ = win32pipe.PeekNamedPipe(self.process.raw.output, 0)
            except pywintypes.error as exc:
                if exc.winerror == 109:
                    return b''
                raise OSError(exc.winerror, str(exc)) from exc
            if available:
                return self.process.raw.read(min(size, available))
            await asyncio.sleep(0.01)


class NativeProcess:
    def __init__(self, raw, resources, storage_lease):
        self.raw, self.resources = raw, resources
        self.storage_lease = storage_lease
        self.pid, self.staged_root = raw.pid, resources.stage_root
        self.stdout = NativeOutput(self)

    @property
    def returncode(self):
        if win32event.WaitForSingleObject(self.raw.process, 0) == win32event.WAIT_TIMEOUT:
            return None
        return win32process.GetExitCodeProcess(self.raw.process)

    async def wait(self):
        while self.returncode is None:
            await asyncio.sleep(0.01)
        return self.returncode

    def kill(self):
        self.raw.terminate_tree()


class WindowsSandbox:
    def unavailable_reason(self):
        return 'the Windows LPAC command sandbox is pending native acceptance; commands stay disabled and there is no unsandboxed fallback'

    def __init__(self):
        self.runtime = Path(sys.base_prefix)

    def executable(self):
        candidate = self.runtime / 'python.exe'
        if not NATIVE_ACCEPTED or not candidate.is_file():
            return None
        try:
            with self._provider().open():
                return str(candidate)
        except (OSError, ValueError):
            return None

    def _provider(self):
        from isycode.windows_sandbox_storage_cli import configured_storage
        return BoundedStorageProvider(configured_storage())

    def identity(self):
        from isycode.platform_windows_sandbox_resources import runtime_files
        digest = hashlib.sha256()
        for relative, path in runtime_files(self.runtime):
            digest.update(relative.encode('utf-8') + b'\0')
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        with self._provider().open() as lease:
            storage = lease.identity.payload()
        return {'backend': 'windows-lpac-job/2', 'capabilities': ('registryRead',),
                'runtime_sha256': digest.hexdigest(), 'storage': storage}

    def resolve_program(self, root, name):
        if name in {'python', 'python3', 'py', str(self.runtime / 'python.exe')}:
            return 'runtime/python.exe'
        raise ValueError('native sandbox currently supports its explicit CPython runtime only')

    def program_valid(self, program, argv0):
        try:
            return program == self.resolve_program(Path('.'), argv0)
        except ValueError:
            return False

    def relative_path_valid(self, value):
        path = PureWindowsPath(value)
        reserved = {'con', 'prn', 'aux', 'nul', 'conin$', 'conout$',
            *(f'com{i}' for i in '123456789¹²³'), *(f'lpt{i}' for i in '123456789¹²³')}
        return (not path.drive and not path.root and ':' not in value
                and all(part.rstrip(' .') == part and part.split('.')[0].casefold() not in reserved
                        for part in path.parts))

    async def start(self, staging, program, argv, cwd, masks, timeout_s, *,
                    executable=None, identity=None):
        if not self.program_valid(program, argv[0]):
            raise ValueError('unreviewed native program')
        if not self.relative_path_valid(cwd):
            raise ValueError('cwd is outside native staging')
        if identity is None or identity.get('backend') != 'windows-lpac-job/2':
            raise StorageUnavailableError('approved bounded storage identity is required')
        try:
            expected = StorageIdentity(**identity['storage'])
            runtime_digest = identity['runtime_sha256']
            if not isinstance(runtime_digest, str) or len(runtime_digest) != 64:
                raise ValueError('invalid approved runtime digest')
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageUnavailableError('approved bounded storage identity is invalid') from exc
        lease = self._provider().open(expected)
        task = asyncio.create_task(asyncio.to_thread(
            WindowsSandboxResources.prepare, staging, self.runtime, masks,
            runtime_digest, storage_lease=lease))
        try:
            resources = await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                try:
                    abandoned = await task
                except (OSError, ValueError):
                    pass
                else:
                    await asyncio.to_thread(abandoned.close)
            finally:
                lease.close()
            raise
        except BaseException:
            lease.close()
            raise
        try:
            exe = resources.runtime_root / 'python.exe'
            target = resources.stage_root if cwd == '.' else resources.stage_root / cwd
            target.relative_to(resources.stage_root)
            lease.assert_directory(resources.scratch_root)
            raw = WindowsSandboxProcess.launch(exe, (str(exe), *argv[1:]), target,
                resources.environment, resources.profile_sid, 256, resources.capability_sids)
            return NativeProcess(raw, resources, lease)
        except BaseException:
            try:
                resources.close()
            finally:
                lease.close()
            raise

    def terminate(self, process):
        process.kill()

    async def finish(self, process):
        process.kill()
        await process.wait()
        end = asyncio.get_running_loop().time() + 10
        while win32job.QueryInformationJobObject(process.raw.job,
                win32job.JobObjectBasicAccountingInformation)['ActiveProcesses']:
            if asyncio.get_running_loop().time() >= end:
                raise OSError('native process tree termination could not be verified')
            await asyncio.sleep(0.01)
        process.storage_lease.assert_directory(process.resources.scratch_root)

    async def close(self, process):
        failure = None
        for operation in (lambda: self.finish(process), process.raw.close,
                          lambda: asyncio.to_thread(process.resources.close),
                          process.storage_lease.close):
            try:
                result = operation()
                if result is not None and hasattr(result, '__await__'):
                    await result
            except BaseException as exc:
                if failure is None:
                    failure = exc
        if failure is not None:
            raise failure
