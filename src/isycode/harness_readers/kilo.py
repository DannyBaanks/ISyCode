from __future__ import annotations

from pathlib import Path

from isycode.harness_graph import HarnessSetting, SkippedFile
from isycode.harness_readers._shared import load_jsonc
from isycode.harness_readers.opencode import config_rows


HARNESS_ID = "kilo"


def read_root(root: Path) -> tuple[list[HarnessSetting], list[SkippedFile]]:
    """Kilo CLI is an opencode fork: same config schema, in ~/.config/kilo/kilo.jsonc.

    Its auth and sessions live under ~/.local/share/kilo, outside this root,
    so nothing secret is reachable from here.
    """
    config = load_jsonc(Path(root), "kilo.jsonc")
    return config_rows(HARNESS_ID, config, "kilo.jsonc"), []
