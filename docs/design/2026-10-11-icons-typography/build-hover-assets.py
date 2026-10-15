"""Extract preserved Its Hover SVG geometry for the standalone design demo.

Modified adaptation, 2026-10-11: React/Motion wrappers become SVG + Web
Animations API. Original sources, Apache-2.0 license and attribution retained.
"""
from pathlib import Path
import html
import json
import re

ROOT = Path(__file__).resolve().parent
NAMES = {
    "copy": "copy-icon",
    "terminal": "terminal-icon",
    "refresh": "refresh-icon",
    "connection": "plug-connected-icon",
    "shield": "shield-check",
    "check": "simple-checked-icon",
}
out = {}
for name, source in NAMES.items():
    tsx = (ROOT / "sources/itshover/icons" / (source + ".tsx")).read_text()
    tsx = re.sub(r"\{/\*.*?\*/\}", "", tsx, flags=re.S)
    paths = []
    for tag in re.findall(r"<(?:motion\.)?path\b[^>]*?/>", tsx, flags=re.S):
        attrs = {}
        for key in ("d", "className", "stroke", "fill"):
            match = re.search(r'\b' + key + r'="([^"]*)"', tag)
            if match:
                attrs["class" if key == "className" else key] = match[1]
        if source == "simple-checked-icon" and "className=" in tag:
            attrs["class"] = "check-path"
        if "d" not in attrs:
            raise ValueError("Unrecognized path in " + source)
        paths.append("<path " + " ".join(k + '="' + html.escape(v, quote=True) + '"' for k, v in attrs.items()) + "/>")
    if not paths:
        raise ValueError("No source paths found: " + source)
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + "".join(paths) + "</svg>"
    out[name] = svg
    dest = ROOT / "icons/itshover" / (name + ".svg")
    dest.parent.mkdir(parents=True, exist_ok=True)
    notice = "<!-- Copyright 2026 itshover. Apache-2.0; see ../../licenses/itshover-Apache-2.0.txt. Modified 2026-10-11: JSX wrappers removed, geometry retained; motion implemented separately in hover-motion.js. -->\n"
    dest.write_text(notice + svg + "\n")
(ROOT / "itshover-svg.json").write_text(json.dumps(out, indent=2) + "\n")
print("Built 6 Its Hover geometry adaptations; original TSX preserved")
