"""One-shot, private-state Windows reboot/remount acceptance runner."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


REPO = Path(r"C:\Development\ISyCo Git\ISyCode")
PRIVATE_ROOT = Path(r"D:\ISyCode-Sandbox-5ae383aa26a8490ea9910d768b51f4a0")
TASK_NAME = "ISyCode-VHD-Reboot-Acceptance-20261015"
CONFIG_ENV = "ISYCODE_WINDOWS_SANDBOX_STORAGE_CONFIG"
EVIDENCE = REPO / "docs/platform-parity/evidence/windows-vhd-reboot-acceptance-r2-20261015.txt"

sys.path.insert(0, str(REPO / "src"))


def boot_epoch() -> float:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get_ticks = kernel.GetTickCount64
    get_ticks.restype = ctypes.c_ulonglong
    return time.time() - get_ticks() / 1000


def config_path() -> Path:
    pointers = list(PRIVATE_ROOT.rglob("config-path.txt"))
    if len(pointers) != 1:
        raise RuntimeError("private storage configuration pointer is absent or ambiguous")
    selected = Path(pointers[0].read_text(encoding="utf-8").strip())
    if not selected.is_file():
        raise RuntimeError("registered private storage configuration is unavailable")
    os.environ[CONFIG_ENV] = str(selected)
    os.environ["PYTHONPATH"] = str(REPO / "src")
    return selected


def load_config():
    from isycode.windows_sandbox_storage_cli import load_storage_config

    return load_storage_config(config_path())


def identity_digest(identity) -> str:
    payload = json.dumps(identity.payload(), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def marker_path(state_dir: Path) -> Path:
    return state_dir / "pre-reboot-marker.json"


def config_snapshot_path(state_dir: Path) -> Path:
    return state_dir / "post-reboot-config-private.json"


def write_config_snapshot(config, state_dir: Path) -> str:
    if config.registered_identity is None:
        raise RuntimeError("bounded storage lacks a registered identity")
    payload = {
        "volume_guid": config.volume_guid,
        "backing_file": str(config.backing_file),
        "max_bytes": config.max_bytes,
        "registered_identity": config.registered_identity.payload(),
    }
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path = config_snapshot_path(state_dir)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def load_config_snapshot(state_dir: Path, expected_identity_sha256: str):
    from isycode.platform_windows_sandbox_volume import StorageConfig, StorageIdentity

    raw = config_snapshot_path(state_dir).read_bytes()
    payload = json.loads(raw)
    identity = StorageIdentity(**payload["registered_identity"])
    config = StorageConfig(payload["volume_guid"], Path(payload["backing_file"]),
                           payload["max_bytes"], identity)
    if identity_digest(identity) != expected_identity_sha256:
        raise RuntimeError("private post-reboot configuration does not match pre-reboot identity")
    return config, hashlib.sha256(raw).hexdigest()


def scratch_allocations(config) -> list[Path]:
    root = Path(config.volume_guid)
    return [entry for entry in root.iterdir()
            if entry.is_dir() and entry.name.startswith("isycode-lpac-")]


def preflight(state_dir: Path) -> None:
    from isycode.platform_windows_sandbox_volume import BoundedStorageProvider

    config = load_config()
    if config.registered_identity is None:
        raise RuntimeError("bounded storage lacks a registered identity")
    with BoundedStorageProvider(config).open(config.registered_identity) as lease:
        lease.assert_unchanged()
        if lease.identity != config.registered_identity:
            raise RuntimeError("pre-reboot storage identity mismatch")
    snapshot_sha256 = write_config_snapshot(config, state_dir)
    allocations = scratch_allocations(config)
    if allocations:
        raise RuntimeError("owned scratch remains; recover it before reboot acceptance")
    marker = {
        "schema": "isycode.vhd-reboot-acceptance/1",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "boot_epoch": boot_epoch(),
        "identity_sha256": identity_digest(config.registered_identity),
        "config_snapshot_sha256": snapshot_sha256,
    }
    marker_path(state_dir).write_text(json.dumps(marker, sort_keys=True) + "\n", encoding="utf-8")
    print("PRE_REBOOT=PASS; REGISTERED_IDENTITY=PASS; OWNED_SCRATCH=0")


def run_operator_attachment(config, state_dir: Path, image_attached: bool) -> str:
    identity = config.registered_identity
    helper = REPO / "scripts/attach-windows-sandbox-volume.py"
    if image_attached:
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        command = [
            str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(REPO / "scripts/remount-windows-sandbox-volume.ps1"),
            "-ImagePath", str(config.backing_file),
            "-ExpectedImageId", identity.image_identifier,
            "-ExpectedVolume", identity.volume_guid,
            "-PythonPath", sys.executable,
            "-AttachHelper", str(helper),
        ]
        mode = "attached-image-verified-and-remounted"
    else:
        command = [
            sys.executable, str(helper), "--image", str(config.backing_file),
            "--expected-image-id", identity.image_identifier, "--new-attachment",
        ]
        mode = "detached-image-verified-and-attached"
    result = subprocess.run(command, cwd=REPO, capture_output=True, text=True,
                            timeout=180, env=os.environ.copy())
    raw = result.stdout + result.stderr
    (state_dir / "operator-attachment-private.log").write_text(raw, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"operator attachment helper failed with exit {result.returncode}")
    return mode


def after_reboot(state_dir: Path) -> None:
    from isycode.platform_windows_sandbox_volume import (
        BoundedStorageProvider,
        validate_observation,
    )
    from isycode.platform_windows_sandbox_volume_api import inspect_image, inspect_volume
    from isycode.platform_windows_sandbox import NATIVE_ACCEPTED

    summary: dict[str, object] = {"schema": "isycode.vhd-reboot-acceptance-result/1"}
    raw_test = state_dir / "pytest-private.log"
    private_error = state_dir / "failure-private.txt"
    try:
        before = json.loads(marker_path(state_dir).read_text(encoding="utf-8"))
        try:
            config = load_config()
        except (OSError, RuntimeError, ValueError):
            config, snapshot_sha256 = load_config_snapshot(state_dir, before["identity_sha256"])
        else:
            snapshot_sha256 = None
            if before.get("config_snapshot_sha256"):
                saved, snapshot_sha256 = load_config_snapshot(state_dir, before["identity_sha256"])
                if (snapshot_sha256 != before["config_snapshot_sha256"]
                        or identity_digest(saved.registered_identity)
                        != identity_digest(config.registered_identity)):
                    raise RuntimeError("private bootstrap snapshot differs from registered storage")
        identity = config.registered_identity
        if identity is None or identity_digest(identity) != before["identity_sha256"]:
            raise RuntimeError("registered VHD identity differs from pre-reboot marker")
        if before.get("config_snapshot_sha256") and snapshot_sha256:
            if snapshot_sha256 != before["config_snapshot_sha256"]:
                raise RuntimeError("private post-reboot configuration snapshot hash mismatch")
        rebooted = boot_epoch() > float(before["boot_epoch"]) + 60
        if not rebooted:
            raise RuntimeError("system boot time did not advance; no reboot was demonstrated")
        image = inspect_image(config.backing_file)
        if (not image.fixed or image.device_id != 2 or image.virtual_bytes != 512 * 1024**2
                or image.image_identifier != identity.image_identifier
                or image.backing_file_id != identity.backing_file_id):
            raise RuntimeError("backing image does not match the registered fixed VHD")
        mode = run_operator_attachment(config, state_dir, bool(image.physical_device))
        observation = inspect_volume(config)
        if validate_observation(config, observation) != identity:
            raise RuntimeError("post-reboot volume identity or private ownership mismatch")
        with BoundedStorageProvider(config).open(identity) as lease:
            lease.assert_unchanged()
        allocations = scratch_allocations(config)
        if allocations:
            raise RuntimeError("owned scratch appeared across reboot; preserved for diagnosis")
        summary.update({
            "status": "PASS",
            "boot_changed": True,
            "identity_sha256": before["identity_sha256"],
            "config_snapshot_sha256": snapshot_sha256 or before.get("config_snapshot_sha256"),
            "attachment_path": mode,
            "volume_inspection": "PASS",
            "owned_scratch_before_acceptance": 0,
            "native_accepted": bool(NATIVE_ACCEPTED),
        })
        command = [
            sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
            "--basetemp", str(state_dir / "pytest-basetemp"), "-q", "-s", "-rs",
            str(REPO / "tests/test_windows_sandbox_volume_acceptance.py"),
        ]
        result = subprocess.run(command, cwd=REPO, capture_output=True, text=True,
                                timeout=900, env=os.environ.copy())
        raw_test.write_text(result.stdout + result.stderr, encoding="utf-8")
        summary["pytest_exit"] = result.returncode
        match = re.search(r"(\d+ passed[^\r\n]*)", result.stdout + result.stderr)
        summary["pytest_summary"] = match.group(1) if match else "summary unavailable; inspect private log"
        summary["pytest_raw_sha256"] = hashlib.sha256(raw_test.read_bytes()).hexdigest()
        if result.returncode != 0:
            summary["status"] = "FAIL"
            raise RuntimeError("post-reboot real-VHD acceptance selection failed")
    except BaseException as exc:
        summary["status"] = "FAIL"
        summary["error_type"] = type(exc).__name__
        private_error.write_text(repr(exc), encoding="utf-8")
        summary["failure_sha256"] = hashlib.sha256(private_error.read_bytes()).hexdigest()
    finally:
        task_delete = subprocess.run(
            ["schtasks.exe", "/Delete", "/TN", TASK_NAME, "/F"],
            capture_output=True, text=True, timeout=30,
        )
        task_query = subprocess.run(
            ["schtasks.exe", "/Query", "/TN", TASK_NAME],
            capture_output=True, text=True, timeout=30,
        )
        summary["one_shot_task_removed"] = task_query.returncode != 0
        summary["recorded_at_utc"] = datetime.now(timezone.utc).isoformat()
        EVIDENCE.write_text(
            "Windows VHD reboot/remount acceptance\n"
            + json.dumps(summary, sort_keys=True, indent=2)
            + "\n",
            encoding="utf-8",
        )
    if summary.get("status") != "PASS" or not summary.get("one_shot_task_removed"):
        raise SystemExit(1)
    print("POST_REBOOT=PASS; SAME_REGISTERED_VHD=PASS; INSPECTION=PASS; "
          f"ACCEPTANCE={summary.get('pytest_summary')}; ONE_SHOT_TASK_REMOVED=PASS")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("preflight", "after-reboot"))
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    args.state_dir.mkdir(parents=True, exist_ok=True)
    if args.phase == "preflight":
        preflight(args.state_dir)
    else:
        after_reboot(args.state_dir)


if __name__ == "__main__":
    main()
