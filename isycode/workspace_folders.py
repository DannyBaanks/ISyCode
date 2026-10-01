"""User-selected sibling roots; membership never replaces per-root action gates.

Only native user controls call mutation methods. Model tools may select an
already registered alias, never register roots or enable delegated approval.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from pathlib import Path

from isycode.workspace_authority import WorkspaceAuthority
from isycode.workspace_setup import state_root

MAX_FOLDERS = 8
MAX_CONFIG_BYTES = 32 * 1024
ALIAS = re.compile(r'[a-z][a-z0-9_-]{0,31}\Z')
READ_GRANTS = ('workspace.files.list', 'workspace.files.read', 'workspace.files.search')


class WorkspaceFolders:
    def __init__(self, main: Path):
        self.main = Path(main).resolve(strict=True)
        directory = state_root() / 'workspace-folders'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError('Folder settings directory is unsafe')
        if os.name == 'posix':
            directory.chmod(0o700)
        identity = hashlib.sha256(str(self.main).encode()).hexdigest()[:32]
        self.path = directory / f'{identity}.json'

    @staticmethod
    def _identity(path: Path) -> list[int]:
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError('Folder must be a real directory, not a symlink')
        return [info.st_dev, info.st_ino]

    def _load(self) -> dict:
        identity = self._identity(self.main)
        default = {'version': 1, 'main': str(self.main), 'identity': identity,
                   'auto_edit': False, 'folders': []}
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return default
        if (not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CONFIG_BYTES
                or (os.name == 'posix' and (info.st_uid != os.getuid() or info.st_mode & 0o077))):
            raise ValueError('Folder settings are unsafe')
        fd = os.open(self.path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino, opened.st_size) != (info.st_dev, info.st_ino, info.st_size):
                raise ValueError('Folder settings changed during inspection')
            payload = os.read(fd, MAX_CONFIG_BYTES + 1)
            after = os.fstat(fd)
            if (after.st_mtime_ns, after.st_ctime_ns, after.st_size) != (opened.st_mtime_ns, opened.st_ctime_ns, opened.st_size):
                raise ValueError('Folder settings changed while reading')
        finally:
            os.close(fd)
        try:
            data = json.loads(payload)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError('Folder settings are unreadable') from exc
        if (not isinstance(data, dict) or set(data) != set(default)
                or data['version'] != 1 or data['main'] != str(self.main)
                or data['identity'] != identity or type(data['auto_edit']) is not bool
                or not isinstance(data['folders'], list) or len(data['folders']) > MAX_FOLDERS):
            raise ValueError('Folder settings do not match this workspace')
        aliases, paths = set(), set()
        for item in data['folders']:
            if (not isinstance(item, dict) or set(item) != {'alias', 'path', 'editable', 'auto_edit', 'identity'}
                    or not isinstance(item['alias'], str) or not ALIAS.fullmatch(item['alias'])
                    or item['alias'] == 'main' or item['alias'] in aliases
                    or not isinstance(item['path'], str) or len(item['path']) > 4096
                    or Path(item['path']).parent != self.main.parent or item['path'] == str(self.main)
                    or item['path'] in paths or type(item['editable']) is not bool
                    or type(item['auto_edit']) is not bool or (item['auto_edit'] and not item['editable'])
                    or not isinstance(item['identity'], list) or len(item['identity']) != 2
                    or not all(type(n) is int and n >= 0 for n in item['identity'])):
                raise ValueError('Folder registration is malformed')
            aliases.add(item['alias'])
            paths.add(item['path'])
        return data

    def _save(self, data: dict) -> None:
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True).encode()
        if len(payload) > MAX_CONFIG_BYTES:
            raise ValueError('Folder settings exceed the size limit')
        temporary = self.path.parent / ('.folders-' + secrets.token_hex(8))
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def list(self) -> list[dict]:
        return [dict(item) for item in self._load()['folders']]

    def resolve(self, alias: str = 'main', *, write: bool = False) -> Path:
        data = self._load()
        if alias == 'main':
            return self.main
        item = next((item for item in data['folders'] if item['alias'] == alias), None)
        if item is None:
            raise ValueError('Folder alias is not registered')
        root = Path(item['path'])
        try:
            if self._identity(root) != item['identity'] or root.resolve(strict=True) != root:
                raise ValueError('Registered folder identity changed')
        except (OSError, RuntimeError) as exc:
            raise ValueError('Registered folder is unavailable') from exc
        if write and not item['editable']:
            raise ValueError('This attachment is read-only')
        return root

    def add(self, alias: str, path: str, *, editable: bool) -> None:
        data = self._load()
        if (not isinstance(alias, str) or not ALIAS.fullmatch(alias) or alias == 'main'
                or type(editable) is not bool or not isinstance(path, str) or len(path) > 4096):
            raise ValueError('Use an alias like other-project and an absolute sibling folder path')
        root = Path(path).expanduser()
        if not root.is_absolute() or '..' in root.parts or root.parent != self.main.parent or root == self.main:
            raise ValueError('Choose a direct sibling folder, not the shared parent or a child')
        try:
            identity = self._identity(root)
            if root.resolve(strict=True) != root:
                raise ValueError('Symlink folders are not allowed')
        except (OSError, RuntimeError) as exc:
            raise ValueError('Folder is unavailable') from exc
        if len(data['folders']) >= MAX_FOLDERS:
            raise ValueError('At most eight additional folders are allowed')
        if any(item['alias'] == alias or item['path'] == str(root) for item in data['folders']):
            raise ValueError('Folder or alias is already registered')
        authority = WorkspaceAuthority(root)
        for action in READ_GRANTS + (('workspace.files.write',) if editable else ()):
            authority.set_grant(action, enabled=True, path_prefixes=[str(root)])
        data['folders'].append({'alias': alias, 'path': str(root), 'editable': editable,
                                'auto_edit': False, 'identity': identity})
        self._save(data)

    def remove(self, alias: str) -> None:
        data = self._load()
        if alias == 'main' or not any(item['alias'] == alias for item in data['folders']):
            raise ValueError('Additional folder alias is not registered')
        data['folders'] = [item for item in data['folders'] if item['alias'] != alias]
        self._save(data)

    def auto_edit_allowed(self, alias: str = 'main') -> bool:
        data = self._load()
        self.resolve(alias, write=True)
        return data['auto_edit'] if alias == 'main' else next(item['auto_edit'] for item in data['folders'] if item['alias'] == alias)

    def set_auto_edit(self, alias: str, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError('Auto-edit preference must be a boolean')
        data = self._load()
        self.resolve(alias, write=enabled)
        if alias == 'main':
            data['auto_edit'] = enabled
        else:
            next(item for item in data['folders'] if item['alias'] == alias)['auto_edit'] = enabled
        self._save(data)
