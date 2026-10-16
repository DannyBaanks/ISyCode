"""Refresh hashes.json after recording the 2026-10-16 parity follow-up."""
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

root = Path.cwd()
manifest = root / "docs/platform-parity/hashes.json"
previous = json.loads(
    subprocess.check_output(
        ["git", "show", "HEAD:docs/platform-parity/hashes.json"], text=True
    )
)
current = json.loads(manifest.read_text(encoding="utf-8"))
paths = set(previous["files"]) | set(current["files"])
shallow_log = "docs/platform-parity/evidence/linux-physical-suite-shallow-20261015.log"
shallow_archive = shallow_log + ".gz"
paths.discard(shallow_log)
paths.add(shallow_archive)
for item in (root / "docs/platform-parity").rglob("*"):
    if item.is_file() and "__pycache__" not in item.parts:
        paths.add(item.relative_to(root).as_posix())
paths.update({"src/isycode/updater.py", "tests/test_updater.py"})
paths.discard("docs/platform-parity/hashes.json")
missing = sorted(name for name in paths if not (root / name).is_file())
if missing:
    print("Missing previously hashed files:", *missing, sep="\n", file=sys.stderr)
    raise SystemExit(2)

record = dict(previous)
record.update({
    "recorded_at": datetime.now(timezone.utc).isoformat(),
    "baseline_commit": previous["baseline_commit"],
    "source_parent_commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip(),
    "environment": {
        "system": platform.platform(),
        "python": platform.python_version(),
    },
    "scope": (
        "PR #52 parity follow-up. Windows updater preserves SYSTEMROOT for "
        "native Git and passes a live proxied ls-remote plus isolated bundled "
        "EXE update --check. Physical Ubuntu full-history non-integration "
        "suite: 2025 passed, 153 skipped, 11 deselected. Temporary proxy "
        "configuration restored to its original SHA-256; package removed, "
        "service stopped, port closed, and temporary SSH key removed. "
        "Five-user matrix waived; NATIVE_ACCEPTED=False and separate-user "
        "ACL, remaining IPC/device cases, runtime staging, power-loss, and "
        "interactive physical parity remain NOT_DEMONSTRATED."
    ),
    "files": {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in sorted(paths)
    },
})
shallow_raw = gzip.decompress((root / shallow_archive).read_bytes())
compressed_entries = {
    entry["path"]: entry
    for entry in previous.get("compressed_raw_evidence", [])
}
compressed_entries[shallow_archive] = {
    "path": shallow_archive,
    "compression": "gzip",
    "original_path": shallow_log,
    "original_size_bytes": len(shallow_raw),
    "original_sha256": hashlib.sha256(shallow_raw).hexdigest(),
    "compressed_size_bytes": (root / shallow_archive).stat().st_size,
    "compressed_sha256": hashlib.sha256((root / shallow_archive).read_bytes()).hexdigest(),
    "verified_lossless": True,
}
record["compressed_raw_evidence"] = [
    compressed_entries[name] for name in sorted(compressed_entries)
]
manifest.write_bytes((json.dumps(record, indent=2) + "\n").encode("utf-8"))
for name, expected in record["files"].items():
    actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"SHA-256 mismatch after writing manifest: {name}")
print(f"verified SHA-256: {len(record['files'])}")
print(f"source_parent_commit: {record['source_parent_commit']}")
