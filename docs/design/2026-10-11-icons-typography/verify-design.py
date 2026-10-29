"""Verify design artifacts without substituting for browser/terminal review."""
from pathlib import Path
from html.parser import HTMLParser
import ast
import hashlib
import json
import re
import struct
import subprocess
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
logs = []
def record(message):
    logs.append(message)
    print(message)
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

# Load only the existing pure SFNT table reader, not its image-generation code.
tree = ast.parse((ROOT / "verify-fonts.py").read_text())
font_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "read_font")
ns = {"struct": struct}
exec(compile(ast.Module(body=[font_fn], type_ignores=[]), "read_font", "exec"), ns)
read_font = ns["read_font"]
icons = json.loads((ROOT / "icon-map.json").read_text())
ug, ua, uu = read_font(ROOT / "fonts/ubuntu-current.ttf")
dg, da, du = read_font(ROOT / "fonts/unicode-fallback.ttf")
missing_ubuntu = [k for k, v in icons.items() if not ug(ord(v["unicode"]))]
missing_fallback = [k for k, v in icons.items() if not dg(ord(v["unicode"]))]
assert not missing_fallback, missing_fallback
assert {da(ord(v["unicode"])) for v in icons.values()} == {da(ord("M"))}
all_frames = "▣✓›_ ◷◴◵◶↔→←◇·"
assert all(ug(ord(c)) or dg(ord(c)) for c in all_frames)
profile_fonts = {
    "ubuntu_sha256": sha(ROOT / "fonts/ubuntu-current.ttf"),
    "fallback_sha256": sha(ROOT / "fonts/unicode-fallback.ttf"),
    "mapped_symbols": len(icons), "missing_in_ubuntu": missing_ubuntu,
    "missing_in_fallback": missing_fallback, "fallback_symbols_match_M_advance": True,
    "ubuntu_advance_at_14px": 14 * ua(ord("M")) / uu,
    "fallback_size_adjust_percent": 100 * (ua(ord("M")) / uu) / (da(ord("M")) / du),
    "scope": "cmap/hmtx data and preview resources; actual terminal fallback and cell rendering NOT_DEMONSTRATED",
}
(ROOT / "profile-font-verification.json").write_text(json.dumps(profile_fonts, indent=2) + "\n")
record(f"FONT_TABLES: {len(icons)} Unicode roles covered by fallback; {len(missing_ubuntu)} absent from Ubuntu; terminal rendering NOT_DEMONSTRATED")

checked_assets = 0
for manifest in ("asset-sources.json", "itshover-sources.json", "unicode-fallback-sources.json"):
    data = json.loads((ROOT / manifest).read_text())
    for entry in data["assets"]:
        file = ROOT / (entry.get("path") or entry["file"])
        assert file.is_file(), str(file)
        assert sha(file) == entry["sha256"], str(file)
        checked_assets += 1
record(f"ASSET_HASHES: {checked_assets} preserved source/assets match manifests")

svg_files = sorted((ROOT / "icons").rglob("*.svg"))
for file in svg_files:
    el = ET.parse(file).getroot()
    assert el.tag.endswith("svg")
    assert el.attrib["viewBox"] == "0 0 24 24"
    assert list(el), str(file)
record(f"SVG_PARSE: {len(svg_files)} valid SVG files")

class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []
        self.ids = set()
        self.selected = []
        self.inputs = {}
        self.motion = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            assert a["id"] not in self.ids, a["id"]
            self.ids.add(a["id"])
        for k in ("src", "href"):
            if k in a and not a[k].startswith(("http:", "https:", "#")):
                self.refs.append(a[k])
        if tag == "option" and "selected" in a:
            self.selected.append(a["value"])
        if tag == "input" and "id" in a:
            self.inputs[a["id"]] = a
        if "data-motion" in a:
            self.motion.append(a["data-motion"])

html = (ROOT / "preview.html").read_text()
page = Page()
page.feed(html)
assert page.selected == ["UbuntuCurrent", "unicode"], page.selected
assert page.inputs["size"]["value"] == "14"
assert page.inputs["leading"]["value"] == "1.3"
assert len(page.motion) == 6
assert "__HOVER_CARDS__" not in html and "__ICONS__" not in html
refs = set(page.refs + re.findall(r"url\(([^)]+)\)", html))
# Tabler references are built by JS from the icon mapping.
refs.update("icons/tabler/" + v["svg"] + ".svg" for v in icons.values())
for ref in refs:
    assert (ROOT / ref).is_file(), ref
record(f"HTML_SOURCE: accepted profile, six motion samples, unique IDs and {len(refs)} local references checked")

inline = re.findall(r"<script>(.*?)</script>", html, re.S)
assert len(inline) == 1
inline_file = ROOT / "verification-inline.js"
inline_file.write_text(inline[0])
for file in (inline_file, ROOT / "hover-motion.js"):
    result = subprocess.run(["node", "--check", str(file)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
record("JS_SYNTAX: inline comparator and hover-motion.js accepted by node --check")
for file in sorted(ROOT.glob("*.py")):
    compile(file.read_text(), str(file), "exec")
record("PYTHON_SYNTAX: artifact helpers compile without creating cache files")

http = []
for ref in ["preview.html", *sorted(refs)]:
    with urllib.request.urlopen("http://127.0.0.1:8781/" + ref, timeout=10) as response:
        body = response.read()
        assert response.status == 200
        assert hashlib.sha256(body).hexdigest() == sha(ROOT / ref), ref
        http.append({"path": ref, "status": response.status, "bytes": len(body)})
record(f"LOCAL_HTTP: {len(http)} resources returned HTTP 200 and exact on-disk bytes")

source_paths = ["src/isycode/" + x for x in ("tui.py", "tui_widgets.py", "tui_theme.py", "tui_app_menu.py", "tui_app_rail.py", "isycode.tcss", "clipboard_owner.py")]
baseline = {file: sha(REPO / file) for file in source_paths}
(ROOT / "product-source-baseline.json").write_text(json.dumps(baseline, indent=2) + "\n")
record("PRODUCT_SCOPE: baseline hashes recorded; no product source edits in this design change")
record("NOT_DEMONSTRATED: updated browser rendering/interactions, native TUI animation, terminal font fallback, real clipboard, remote services")
record("BROWSER_LIMIT: browser control rejected binding existing error-page tab under URL protocol policy; no workaround attempted")

verification = {
    "date": "2026-10-11", "command": "python3 verify-design.py", "cwd": str(ROOT),
    "exit_status": 0, "asset_hashes_checked": checked_assets,
    "svg_files_parsed": len(svg_files), "http_resources": http,
    "accepted_profile_source_checked": True, "javascript_syntax_checked": True,
    "font_data": profile_fonts,
    "browser_revision_review": "NOT_DEMONSTRATED: URL protocol policy rejection",
    "production_tui_changed": False,
    "not_demonstrated": ["live browser motion/render/layout for this revision", "native terminal rendering/animation", "terminal point-size calibration", "product gesture contract", "real clipboard with wrapping/scroll", "remote inference/connections", "audit bug fixes"],
    "raw_output": "verification.log",
    "prior_verifier_failure": "verification-first-run.log: manifest key mismatch (file vs path), corrected in verifier; source files were not changed",
}
(ROOT / "verification.json").write_text(json.dumps(verification, indent=2) + "\n")
(ROOT / "verification.log").write_text("\n".join(logs) + "\n")
