"""Optional native RTK adapter. RTK owns rewriting and filtering, never authority.

The approved command runs once, unchanged. Its bounded raw output is archived
before native `rtk pipe` filters it in an empty, network-denied sandbox. This
avoids executing RTK's rewritten command with different flags or losing raw
success output (RTK's default recall mode only retains failures/truncations).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path
from collections.abc import Mapping

from isycode.workspace_setup import state_root

MAX_BINARY_BYTES = 32 * 1024**2
MAX_CAPTURE_BYTES = 2 * 1024**2
HASH = re.compile(r'[0-9a-f]{64}\Z')
_STATS: OrderedDict[str, tuple[int, int]] = OrderedDict()
_STATS_LOCK = threading.Lock()


def _directory(name: str) -> Path:
    base = state_root() / 'rtk'
    path = base / name
    # Validate each parent before creating anything beneath it.
    for directory in (base, path):
        directory.mkdir(mode=0o700, parents=directory == base, exist_ok=True)
        info = directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or (os.name == 'posix' and
                (info.st_uid != os.getuid() or info.st_mode & 0o077))):
            raise ValueError('RTK private state directory is unsafe')
    return path


def _read(path: Path, limit: int, *, private: bool = False) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0))
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_size > limit
                or (private and (info.st_nlink != 1 or (os.name == 'posix' and
                                 (info.st_uid != os.getuid() or info.st_mode & 0o077))))):
            raise ValueError('RTK file is unsafe or too large')
        data = bytearray()
        while chunk := os.read(fd, min(65536, limit + 1 - len(data))):
            data.extend(chunk)
            if len(data) > limit:
                raise ValueError('RTK file exceeds its size limit')
        after = os.fstat(fd)
        if (after.st_size != info.st_size or after.st_mtime_ns != info.st_mtime_ns
                or after.st_ctime_ns != info.st_ctime_ns):
            raise ValueError('RTK file changed during inspection')
        return bytes(data)
    finally:
        os.close(fd)


def discover() -> str | None:
    # Prefer the system installation; pin a canonical user installation too.
    for candidate in ('/usr/local/bin/rtk', '/usr/bin/rtk', shutil.which('rtk')):
        if candidate:
            path = Path(candidate).resolve()
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
    return None


def _binary(identity: Mapping) -> bytes:
    path = identity.get('path')
    if not isinstance(path, str) or not os.path.isabs(path):
        raise ValueError('RTK executable path is invalid')
    content = _read(Path(path), MAX_BINARY_BYTES)
    if hashlib.sha256(content).hexdigest() != identity.get('sha256'):
        raise ValueError('RTK binary changed; enable it again after reviewing its identity')
    return content


def _cli(identity: Mapping, args: tuple[str, ...], raw: bytes = b'') -> tuple[int, bytes]:
    """Run only the pinned RTK bytes; no host fallback, config, project or network."""
    from isycode.command_runner import sandbox_command, sandbox_executable
    sandbox = sandbox_executable()
    if sandbox is None:
        raise ValueError('RTK needs the command sandbox')
    content = _binary(identity)
    with tempfile.TemporaryDirectory(prefix='isycode-rtk-') as directory:
        base = Path(directory)
        binary = base / 'rtk'
        binary.write_bytes(content)
        binary.chmod(0o500)
        empty = base / 'empty'
        empty.mkdir()
        command = sandbox_command(sandbox, empty, '/rtk/rtk', ('rtk', *args), '.', (), timeout_s=5)
        separator = command.index('--')
        command[separator:separator] = ['--ro-bind', str(binary), '/rtk/rtk',
                                      '--setenv', 'RTK_TEE', '0',
                                      '--setenv', 'RTK_RECALL', '0']
        # Files bound output memory even if a pinned third-party binary misbehaves.
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(command, cwd='/', stdin=subprocess.PIPE,
                                       stdout=output, stderr=errors, start_new_session=True)
            try:
                process.communicate(input=raw, timeout=7)
            except BaseException:
                try:
                    import signal
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                raise
            if output.tell() > MAX_CAPTURE_BYTES or errors.tell() > MAX_CAPTURE_BYTES:
                raise ValueError('RTK output exceeds its size limit')
            output.seek(0)
            return process.returncode, output.read(MAX_CAPTURE_BYTES)


class Settings:
    """Explicit user opt-in pinned to a binary, not a Workspace Authority grant."""

    def __init__(self):
        self.path = _directory('settings') / 'native.json'

    def load(self) -> dict:
        try:
            data = json.loads(_read(self.path, 8192, private=True))
        except FileNotFoundError:
            return {'enabled': False}
        if not isinstance(data, dict) or type(data.get('enabled')) is not bool:
            raise ValueError('RTK settings are invalid')
        if data['enabled'] and not valid_identity(data):
            raise ValueError('RTK identity is invalid')
        return data

    def _save(self, data: dict) -> dict:
        self.load()  # Never replace an unsafe settings file or link.
        # Private, atomic replacement of our one settings file only.
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix='native-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return data

    def inspect(self) -> dict:
        path = discover()
        if path is None:
            raise ValueError('RTK is not installed')
        content = _read(Path(path), MAX_BINARY_BYTES)
        identity = {'enabled': True, 'path': path,
                    'sha256': hashlib.sha256(content).hexdigest()}
        code, version = _cli(identity, ('--version',))
        if code != 0 or re.fullmatch(rb'rtk [0-9]+\.[0-9]+\.[0-9]+[^\r\n]{0,80}\s*', version) is None:
            raise ValueError('RTK version cannot be verified in the sandbox')
        identity['version'] = version.decode().strip()
        _binary(identity)
        return identity

    def enable(self, *, expected: dict | None = None) -> dict:
        identity = self.inspect()
        if expected is not None and identity != expected:
            raise ValueError('RTK binary changed since it was displayed')
        return self._save(identity)

    def disable(self) -> dict:
        return self._save({'enabled': False})


def valid_identity(value: Mapping) -> bool:
    return (isinstance(value.get('path'), str) and os.path.isabs(value['path'])
            and os.path.normpath(value['path']) == value['path']
            and isinstance(value.get('sha256'), str) and HASH.fullmatch(value['sha256']) is not None
            and isinstance(value.get('version'), str) and len(value['version']) <= 100
            and value['version'].startswith('rtk '))


def valid_plan(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    from isycode.action_runtime import command_argv_valid
    return (set(value) == {'path', 'sha256', 'version', 'strategy', 'decision', 'rewrite_argv'}
            and valid_identity(value) and value['strategy'] == 'pipe'
            and value['decision'] in {'allow', 'ask'}
            and command_argv_valid(value['rewrite_argv']) and value['rewrite_argv'][0] == 'rtk'
            and not any(arg in {'|', '||', '&&', ';', '>', '<', '&'} for arg in value['rewrite_argv']))


def plan(argv: tuple[str, ...], program: str) -> dict | None:
    if os.name != 'posix':
        return None
    identity = Settings().load()
    if not identity['enabled']:
        return None
    _binary(identity)
    if program.startswith('/workspace/') or Path(argv[0]).name == 'rtk':
        return None
    query = shlex.join((Path(argv[0]).name, *argv[1:]))
    code, rewritten = _cli(identity, ('rewrite', query))
    if code == 1 and not rewritten.strip():
        return None
    if code not in (0, 3) or len(rewritten) > 16384:
        raise ValueError('RTK rewrite failed; command was not executed')
    try:
        tokens = tuple(shlex.split(rewritten.decode('utf-8')))
    except (UnicodeError, ValueError) as exc:
        raise ValueError('RTK rewrite is invalid') from exc
    value = {key: identity[key] for key in ('path', 'sha256', 'version')}
    value.update(strategy='pipe', decision='ask' if code == 3 else 'allow', rewrite_argv=tokens)
    if not valid_plan(value):
        raise ValueError('RTK rewrite is outside the argv contract')
    return value


def _filter_args(value: Mapping) -> tuple[str, ...]:
    """CLI routing only; all filtering implementations remain in upstream RTK."""
    args = value['rewrite_argv'][1:]
    if not args:
        return ('pipe',)
    route = '-'.join(args[:2]) if args[0] in {'git', 'cargo', 'go', 'ruff'} else args[0]
    supported = {'cargo-test', 'pytest', 'go-test', 'go-build', 'ctest', 'tsc', 'vitest',
                 'grep', 'rg', 'find', 'git-log', 'git-diff', 'git-status', 'log', 'mypy',
                 'ruff-check', 'ruff-format', 'prettier', 'phpunit', 'pest', 'paratest',
                 'ecs', 'phpstan', 'pint'}
    return ('pipe', '--filter', route) if route in supported else ('pipe',)


def _artifact(data: bytes, suffix: str) -> Path:
    digest = hashlib.sha256(data).hexdigest()
    path = _directory('outputs') / (digest + suffix)
    if not path.exists():
        entries = list(path.parent.iterdir())
        if len(entries) >= 1024 or sum(f.lstat().st_size for f in entries) + len(data) > 64 * 1024**2:
            raise ValueError('RTK evidence quota reached; disable RTK or preserve and manage its artifacts')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    except FileExistsError:
        if _read(path, MAX_CAPTURE_BYTES, private=True) != data:
            raise ValueError('RTK output artifact failed verification')
    else:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    return path


async def finish(value: Mapping, result: dict, raw: bytes) -> None:
    """Archive the exact captured bytes and compact only the model-visible text."""
    path = await asyncio.to_thread(_artifact, raw, '.bin')
    before = result['output']
    compact, fallback = before, ''
    if not result.get('output_truncated') and not result.get('timed_out'):
        try:
            code, output = await asyncio.to_thread(_cli, value, _filter_args(value), raw)
            if code == 0:
                decoded = output.decode('utf-8')
                if len(output) <= len(before.encode('utf-8')) and (not raw or output.strip()):
                    compact = decoded
                else:
                    fallback = 'filter did not reduce output'
            else:
                fallback = 'filter failed; original output retained'
        except (OSError, ValueError, subprocess.TimeoutExpired, UnicodeError):
            fallback = 'filter unavailable; original output retained'
    else:
        fallback = 'incomplete output; original output retained'
    result['output'] = compact
    result['rtk'] = {
        'path': value['path'], 'sha256': value['sha256'], 'version': value['version'],
        'strategy': 'pipe', 'rewrite_argv': list(value['rewrite_argv']),
        'filter_argv': ['rtk', *_filter_args(value)], 'applied': compact != before,
        'raw_sha256': path.stem, 'captured_bytes': len(raw),
        'raw_complete': not result.get('output_truncated', False) and not result.get('timed_out', False),
        'model_bytes': len(compact.encode('utf-8')),
        'saved_bytes': max(0, len(before.encode('utf-8')) - len(compact.encode('utf-8'))),
        'fallback': fallback,
    }


def archive_result(result: dict) -> Path:
    data = json.dumps(result, ensure_ascii=False, sort_keys=True).encode('utf-8')
    return _artifact(data, '.json')


def record_stats(root: Path, result: dict) -> None:
    value = result.get('rtk')
    if not value:
        return
    key = str(root)
    with _STATS_LOCK:
        captured, saved = _STATS.pop(key, (0, 0))
        _STATS[key] = captured + value['captured_bytes'], saved + value['saved_bytes']
        if len(_STATS) > 128:
            _STATS.popitem(last=False)


def savings_label(root: Path) -> str:
    with _STATS_LOCK:
        captured, saved = _STATS.get(str(root), (0, 0))
    return f'RTK ~{saved // 4:,} tok saved ({round(100 * saved / captured) if captured else 0}%)'
