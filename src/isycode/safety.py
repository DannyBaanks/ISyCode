#!/usr/bin/env python3
"""ISyCode Safety Substrate — destructive-action firewall.

Contract:
    REQUEST -> RESOLVE -> PREFLIGHT -> POLICY -> APPROVAL (when required)
            -> EXECUTE -> VERIFY -> RECEIPT

The model can PROPOSE a destructive operation. It can never decide its
own blast radius. The host resolves it first.
"""
from __future__ import annotations

import os
import json
import hashlib
import time
import shutil
from dataclasses import dataclass, field, asdict
from typing import Any, Sequence
from pathlib import Path


@dataclass(frozen=True)
class CanonicalTarget:
    original: str
    canonical: str
    is_symlink: bool = False
    is_junction: bool = False
    crosses_mount: bool = False
    is_protected: bool = False
    size_bytes: int | None = None


@dataclass
class BlastRadiusManifest:
    operation: str
    targets: list[CanonicalTarget]
    count: int
    total_bytes: int | None
    crosses_links: bool
    crosses_mounts: bool
    protected_collisions: list[str]
    policy_decision: str
    sealed_at: float = 0.0
    seal: str = ""

    def to_dict(self) -> dict:
        return {
            "operation": self.operation,
            "targets": [asdict(t) for t in self.targets],
            "count": self.count,
            "total_bytes": self.total_bytes,
            "crosses_links": self.crosses_links,
            "crosses_mounts": self.crosses_mounts,
            "protected_collisions": self.protected_collisions,
            "policy_decision": self.policy_decision,
            "sealed_at": self.sealed_at,
            "seal": self.seal,
        }


@dataclass
class Budget:
    max_files: int | None = None
    max_bytes: int | None = None
    max_directories: int | None = None
    max_depth: int | None = None
    allowed_operations: set[str] = field(default_factory=set)

    def check(self, manifest: BlastRadiusManifest) -> tuple[bool, str]:
        if self.max_files is not None and manifest.count > self.max_files:
            return False, f"file count {manifest.count} exceeds budget {self.max_files}"
        if self.max_bytes is not None and (manifest.total_bytes or 0) > self.max_bytes:
            return False, f"byte total {manifest.total_bytes} exceeds budget {self.max_bytes}"
        if self.allowed_operations and manifest.operation not in self.allowed_operations:
            return False, f"operation {manifest.operation} not in allowed set"
        return True, ""


@dataclass
class SafetyReceipt:
    intent: str
    capability: str
    manifest: dict
    policy: str
    lease_id: str | None
    approval: str | None
    executed: bool
    actual_effects: list[str]
    partial_failures: list[str]
    verification: str
    digest: str
    timestamp: float = 0.0


def _is_protected(path: Path) -> bool:
    protected_markers = [".git", ".isycode", "receipts", "provenance",
                         "state.json", "session.json"]
    parts = path.parts
    for marker in protected_markers:
        if marker in parts:
            return True
    return False


def resolve_canonical(path: str, root: str) -> CanonicalTarget:
    """Resolve a path to canonical form, detecting escapes.

    Handles relative paths, symlinks, junctions/reparse points,
    mount boundaries. Never assumes followlinks=false is sufficient.
    """
    p = Path(path)
    r = Path(root).resolve()
    try:
        real = p.resolve(strict=False)
    except (OSError, RuntimeError):
        real = p.absolute()
    try:
        real.relative_to(r)
        escapes = False
    except ValueError:
        escapes = True
    is_symlink = p.is_symlink() or any(
        part.is_symlink() for part in p.parents if part != p)
    is_junction = False
    if os.name == "nt":
        import stat
        try:
            if p.exists() and (os.lstat(p).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                is_junction = True
        except (OSError, AttributeError):
            pass
    crosses_mount = False
    try:
        if os.path.ismount(str(real)):
            crosses_mount = True
    except OSError:
        pass
    protected = _is_protected(real)
    size = None
    try:
        if real.is_file():
            size = real.stat().st_size
    except OSError:
        pass
    return CanonicalTarget(
        original=path, canonical=str(real), is_symlink=is_symlink,
        is_junction=is_junction, crosses_mount=crosses_mount,
        is_protected=protected, size_bytes=size,
    )


def build_manifest(operation: str, paths: Sequence[str], root: str,
                   policy_decision: str = "PENDING") -> BlastRadiusManifest:
    """Build a blast-radius manifest before any destructive execution."""
    targets = [resolve_canonical(p, root) for p in paths]
    count = len(targets)
    if all(t.size_bytes is not None for t in targets):
        total_bytes = sum(t.size_bytes or 0 for t in targets)
    else:
        total_bytes = None
    crosses_links = any(t.is_symlink or t.is_junction for t in targets)
    crosses_mounts = any(t.crosses_mount for t in targets)
    protected = [t.canonical for t in targets if t.is_protected]
    return BlastRadiusManifest(
        operation=operation, targets=targets, count=count,
        total_bytes=total_bytes, crosses_links=crosses_links,
        crosses_mounts=crosses_mounts, protected_collisions=protected,
        policy_decision=policy_decision,
    )


def seal_manifest(manifest: BlastRadiusManifest) -> str:
    data = json.dumps(manifest.to_dict(), sort_keys=True, default=str)
    return hashlib.sha256(data.encode()).hexdigest()[:16]


class SafetyPolicy:
    """Deny-by-default safety policy."""

    def __init__(self, granted_roots: list[str],
                 protected_roots: list[str] | None = None,
                 budget: Budget | None = None):
        self.granted_roots = [Path(r).resolve() for r in granted_roots]
        self.protected_roots = protected_roots or []
        self.budget = budget or Budget()

    def check(self, manifest: BlastRadiusManifest) -> tuple[bool, str]:
        if manifest.protected_collisions:
            return False, f"protected path collision: {manifest.protected_collisions}"
        if not self.granted_roots:
            return False, "no granted roots configured"
        for t in manifest.targets:
            try:
                Path(t.canonical).relative_to(self.granted_roots[0])
            except ValueError:
                return False, f"target {t.canonical} escapes granted roots"
        ok, reason = self.budget.check(manifest)
        if not ok:
            return False, reason
        if manifest.crosses_links:
            return False, "crosses symlink/junction"
        if manifest.crosses_mounts:
            return False, "crosses mount boundary"
        return True, "ALLOW"


def quarantine(path: str, quarantine_dir: str = "/tmp/isycode-quarantine") -> str:
    os.makedirs(quarantine_dir, exist_ok=True)
    dest = os.path.join(quarantine_dir, f"{int(time.time() * 1000)}-{os.path.basename(path)}")
    shutil.move(path, dest)
    return dest


def make_receipt(intent: str, capability: str, manifest: BlastRadiusManifest,
                 policy: str, lease_id: str | None = None,
                 approval: str | None = None, executed: bool = False,
                 effects: list[str] | None = None,
                 failures: list[str] | None = None) -> SafetyReceipt:
    receipt = SafetyReceipt(
        intent=intent, capability=capability, manifest=manifest.to_dict(),
        policy=policy, lease_id=lease_id, approval=approval,
        executed=executed, actual_effects=effects or [],
        partial_failures=failures or [], verification="PENDING",
        digest="", timestamp=time.time(),
    )
    data = json.dumps({
        "intent": receipt.intent, "capability": receipt.capability,
        "manifest": receipt.manifest, "policy": receipt.policy,
        "lease_id": receipt.lease_id, "approval": receipt.approval,
        "executed": receipt.executed, "actual_effects": receipt.actual_effects,
        "partial_failures": receipt.partial_failures,
        "timestamp": receipt.timestamp,
    }, sort_keys=True, default=str)
    receipt.digest = hashlib.sha256(data.encode()).hexdigest()[:16]
    return receipt
