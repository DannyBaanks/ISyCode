"""Composition boundary for verified workspace effects and recovery."""
import hashlib
import os


def digest(current):
    return None if current is None else hashlib.sha256(current[0]).hexdigest()


if os.name == 'nt':
    from isycode.platform_windows_effect_fs import apply_file, read_file
else:
    from isycode.platform_posix_effect_fs import apply_file, read_file
