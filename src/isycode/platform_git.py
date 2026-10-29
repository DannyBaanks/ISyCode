"""Trusted Git discovery and process environment, selected at composition."""
import os
from pathlib import Path


class PosixGit:
    def discover(self, directories):
        for folder in directories:
            candidate = Path(folder) / 'git'
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        return None

    def environment(self, directories):
        return {'PATH': os.pathsep.join(directories)}


if os.name == 'nt':
    from isycode.platform_windows_git import WindowsGit
    git_platform = WindowsGit()
else:
    git_platform = PosixGit()
