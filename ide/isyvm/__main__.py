"""Allow ``python -m isyvm`` to behave like the installed CLI."""

import sys

from . import isycode_main


if __name__ == "__main__":
    sys.exit(isycode_main())
