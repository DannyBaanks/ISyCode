"""Native clipboard composition; grants and receipts remain in ClipboardOwner."""
import os

if os.name == 'nt':
    from isycode.platform_windows_clipboard import encode_text, read_system_clipboard, system_clipboard_command
else:
    from isycode.platform_posix_clipboard import encode_text, read_system_clipboard, system_clipboard_command
