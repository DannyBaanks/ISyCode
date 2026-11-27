"""ISyCode IDE: native desktop entry, independent of the official isycode CLI."""

__version__ = "0.4.0"


def main() -> int:
    from .__main__ import main as entry
    return entry()
