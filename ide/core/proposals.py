"""Host-owned, single-file changes prepared before approval and checked on apply."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from contextlib import nullcontext

from core.ide_state import atomic_write, project_state, state_lock
from core.resident.store import utc_now


class ProposalError(ValueError):
    pass


@dataclass(frozen=True)
class ChangeProposal:
    id: str
    path: str
    operation: str
    before_sha256: str | None
    before: str
    after: str
    file_mode: int
    created: str

    @property
    def diff(self) -> str:
        diff = "".join(difflib.unified_diff(self.before.splitlines(True), self.after.splitlines(True),
                                          "a/" + self.path, "b/" + self.path))
        return diff or "(sin cambios)"


@dataclass(frozen=True)
class ChangeSet:
    id: str
    changes: tuple[ChangeProposal, ...]
    created: str
    source: str

    @property
    def diff(self):
        return "\n\n".join(f"Archivo: {change.path}\nBase SHA-256: {change.before_sha256 or 'nuevo'}\n{change.diff}" for change in self.changes)


class ProposalService:
    """No deletions, renames or implicit approval; atomic replacement of one file.

    Other host editors must participate in the workspace lock. Hash checks
    catch stale external edits; this is not a CAS guarantee against a hostile
    concurrent process mutating the filesystem after the final check.
    """

    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).resolve()
        self.root = project_state(self.workspace) / "proposals"

    def _state_path(self, filename: str) -> Path:
        if self.root.resolve() != self.workspace / ".isycode-ide" / "proposals":
            raise ProposalError("HOST_STATE_SYMLINK: el estado no puede atravesar enlaces simbólicos")
        return self.root / filename

    def _path(self, value: str) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ProposalError("PATH_REQUIRED: falta la ruta del archivo")
        path = Path(value)
        if not path.is_absolute():
            path = self.workspace / path
        try:
            relative = path.resolve().relative_to(self.workspace)
        except ValueError:
            raise ProposalError("PATH_OUTSIDE_WORKSPACE: la ruta sale del proyecto") from None
        if not relative.parts or any(part in {".git", ".isyvm", ".isycode-ide"} for part in relative.parts):
            raise ProposalError("HOST_STATE_PROTECTED: esta ruta pertenece al host")
        lexical = Path(os.path.abspath(path))
        if path.resolve() != lexical:
            raise ProposalError("SYMLINK_NOT_ALLOWED: la propuesta no puede atravesar enlaces simbólicos")
        if path.exists() and not path.is_file():
            raise ProposalError("NOT_A_FILE: la ruta no es un archivo")
        return self.workspace / relative

    def _read(self, path: Path) -> tuple[str, str | None, int]:
        if not path.exists():
            return "", None, 0o644
        if path.stat().st_size > 2_000_000:
            raise ProposalError("FILE_TOO_LARGE: prepara un cambio en un archivo menor de 2 MB")
        with path.open("rb") as stream:
            raw = stream.read(2_000_001)
            mode = stat.S_IMODE(os.fstat(stream.fileno()).st_mode)
        if len(raw) > 2_000_000:
            raise ProposalError("FILE_TOO_LARGE: el archivo supera 2 MB")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise ProposalError("TEXT_REQUIRED: este flujo solo admite texto UTF-8") from None
        return text, hashlib.sha256(raw).hexdigest(), mode

    def prepare(self, operation: str, arguments: dict) -> ChangeProposal:
        if operation not in {"write", "edit"}:
            raise ProposalError("INVALID_OPERATION: solo write/edit generan propuestas")
        path = self._path(arguments.get("path"))
        before, digest, mode = self._read(path)
        if operation == "write":
            after = arguments.get("content")
        else:
            old, new = arguments.get("old"), arguments.get("new")
            if not isinstance(old, str) or not old or not isinstance(new, str):
                raise ProposalError("EDIT_REQUIRED: old debe contener texto y new debe ser una cadena")
            if digest is None:
                raise ProposalError("FILE_NOT_FOUND: el archivo no existe")
            if before.count(old) != 1:
                raise ProposalError("EDIT_AMBIGUOUS: old debe aparecer exactamente una vez; añade contexto")
            after = before.replace(old, new, 1)
        if not isinstance(after, str) or len(after.encode("utf-8")) > 2_000_000:
            raise ProposalError("CONTENT_REQUIRED: el contenido debe ser texto UTF-8 de hasta 2 MB")
        proposal = ChangeProposal(uuid.uuid4().hex, str(path.relative_to(self.workspace)), operation,
                                  digest, before, after, mode, utc_now())
        self._record(proposal, "pending")
        return proposal

    def _record(self, proposal: ChangeProposal, status: str, **extra):
        atomic_write(self._state_path(proposal.id + ".json"), json.dumps(
            {**asdict(proposal), "status": status, **extra}, ensure_ascii=False, indent=2) + "\n")

    def reject(self, proposal: ChangeProposal):
        self._record(proposal, "rejected", decided=utc_now())

    def mark(self, proposal: ChangeProposal, status: str):
        if status not in {"cancelled", "blocked", "stale", "failed"}:
            raise ProposalError("INVALID_STATUS: estado no válido")
        self._record(proposal, status, decided=utc_now())

    def apply(self, proposal: ChangeProposal, *, _locked=False) -> dict:
        with (nullcontext() if _locked else state_lock(project_state(self.workspace) / "workspace-edit.lock", blocking=False)):
            path = self._path(proposal.path)
            _, current, _ = self._read(path)
            if current != proposal.before_sha256:
                self._record(proposal, "stale", decided=utc_now())
                raise ProposalError("STALE_PROPOSAL: el archivo cambió después de preparar el diff")
            self._record(proposal, "applying", decided=utc_now())
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".isycode-change-", dir=path.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(proposal.after.encode("utf-8"))
                    stream.flush()
                    os.fchmod(stream.fileno(), proposal.file_mode & 0o777)
                    os.fsync(stream.fileno())
                # Re-check the target and parent immediately before replacement.
                path = self._path(proposal.path)
                _, current, _ = self._read(path)
                if current != proposal.before_sha256:
                    raise ProposalError("STALE_PROPOSAL: el archivo cambió antes de aplicar")
                os.replace(temporary, path)
            except Exception:
                self._record(proposal, "failed", decided=utc_now())
                raise
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)  # Only this operation's own staging file.
            result = {"proposal_id": proposal.id, "path": proposal.path,
                      "before_sha256": proposal.before_sha256,
                      "after_sha256": hashlib.sha256(proposal.after.encode("utf-8")).hexdigest()}
            self._record(proposal, "applied", decided=utc_now(), receipt=result)
            return result

    def prepare_batch(self, files: dict[str, str], *, expected_bases=None, source="command") -> ChangeSet:
        if not isinstance(files, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in files.items()):
            raise ProposalError("INVALID_CHANGESET: rutas y contenidos deben ser texto")
        if not files or len(files) > 100 or sum(len(value.encode("utf-8")) for value in files.values()) > 10_000_000:
            raise ProposalError("CHANGESET_LIMIT: revisa hasta 100 archivos y 10 MB por grupo")
        changes = []
        seen = set()
        for relative, after in files.items():
            path = self._path(relative)
            normalized = str(path.relative_to(self.workspace))
            if normalized in seen or not isinstance(after, str) or len(after.encode("utf-8")) > 2_000_000:
                raise ProposalError("INVALID_CHANGESET: rutas duplicadas o contenido no válido")
            seen.add(normalized)
            before, digest, mode = self._read(path)
            if expected_bases is not None and expected_bases.get(normalized) != digest:
                raise ProposalError("STALE_COMMAND_BASE: el proyecto cambió durante el comando; su salida no se aplica")
            changes.append(ChangeProposal(uuid.uuid4().hex, normalized, "write", digest, before, after, mode, utc_now()))
        batch = ChangeSet(uuid.uuid4().hex, tuple(changes), utc_now(), source)
        self._record_batch(batch, "pending")
        return batch

    def _record_batch(self, batch, status, **extra):
        atomic_write(self._state_path(batch.id + ".json"), json.dumps(
            {"id": batch.id, "kind": "batch", "path": f"{len(batch.changes)} archivos",
             "operation": "changeset", "created": batch.created, "source": batch.source,
             "before_sha256": None, "changes": [asdict(change) for change in batch.changes],
             "status": status, **extra}, ensure_ascii=False, indent=2) + "\n")

    def reject_batch(self, batch):
        self._record_batch(batch, "rejected", decided=utc_now())

    def mark_batch(self, batch, status):
        if status not in {"cancelled", "blocked", "stale", "failed"}:
            raise ProposalError("INVALID_STATUS: estado no válido")
        self._record_batch(batch, status, decided=utc_now())

    def apply_batch(self, batch):
        receipts = []
        with state_lock(project_state(self.workspace) / "workspace-edit.lock", blocking=False):
            for change in batch.changes:
                _, current, _ = self._read(self._path(change.path))
                if current != change.before_sha256:
                    self._record_batch(batch, "stale", decided=utc_now())
                    raise ProposalError("STALE_CHANGESET: cambió un archivo desde la revisión")
            self._record_batch(batch, "applying", receipts=receipts, decided=utc_now())
            try:
                for change in batch.changes:
                    receipts.append(self.apply(change, _locked=True))
                    self._record_batch(batch, "applying", receipts=receipts, decided=utc_now())
            except BaseException:
                self._record_batch(batch, "partial" if receipts else "failed", receipts=receipts, decided=utc_now())
                raise
            self._record_batch(batch, "applied", receipts=receipts, decided=utc_now())
        return {"proposal_id": batch.id, "status": "applied", "files": receipts}

    def prepare_recovery(self, proposal_id):
        """Prepare an explicit reversal; never reset a partly applied tree."""
        record = self.inspect(proposal_id)
        if record.get("kind") != "batch" or record["status"] not in {"applied", "partial", "applying"}:
            raise ProposalError("RECOVERY_UNAVAILABLE: este grupo no tiene archivos aplicados para revisar")
        applied = {receipt["path"]: receipt for receipt in record.get("receipts", [])}
        files, bases, retained = {}, {}, []
        for change in record["changes"]:
            # A crash may occur after replace and before the receipt is journaled.
            _, current, _ = self._read(self._path(change["path"]))
            after = hashlib.sha256(change["after"].encode()).hexdigest()
            if change["path"] not in applied and current != after:
                continue
            if current != after:
                raise ProposalError("STALE_RECOVERY: un archivo aplicado cambió después; conserva el trabajo y revísalo")
            if change["before_sha256"] is None:
                retained.append(change["path"])
                continue  # Recovery has zero implicit deletion authority.
            files[change["path"]] = change["before"]
            bases[change["path"]] = after
        if not files:
            raise ProposalError("RECOVERY_REQUIRES_MANUAL_REVIEW: solo hay archivos nuevos; se conservan sin borrarlos")
        return self.prepare_batch(files, expected_bases=bases, source="recovery:" + proposal_id), retained

    def list(self) -> list[dict]:
        self._state_path("index")
        if not self.root.exists():
            return []
        out = []
        for path in sorted(self.root.glob("*.json")):
            try:
                if path.is_symlink() or path.stat().st_size > 65_000_000:
                    continue
                data = json.loads(path.read_text())
                if not isinstance(data, dict):
                    continue
                out.append({key: data.get(key) for key in ("id", "path", "operation", "status", "created", "before_sha256")})
            except (OSError, ValueError):
                continue
        return out

    def inspect(self, proposal_id: str) -> dict:
        if not isinstance(proposal_id, str) or not re.fullmatch(r"[0-9a-f]{32}", proposal_id):
            raise ProposalError("INVALID_PROPOSAL: identificador no válido")
        path = self._state_path(proposal_id + ".json")
        if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size > 65_000_000:
            raise ProposalError("INVALID_PROPOSAL: registro no válido")
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("id") != proposal_id:
            raise ProposalError("INVALID_PROPOSAL: registro no válido")
        if record.get("kind") == "batch":
            changes = record.get("changes")
            if not isinstance(changes, list) or not 1 <= len(changes) <= 100:
                raise ProposalError("INVALID_PROPOSAL: grupo no válido")
            parsed = []
            for item in changes:
                if not isinstance(item, dict) or any(not isinstance(item.get(k), str) for k in ("id", "path", "before", "after", "created", "operation")):
                    raise ProposalError("INVALID_PROPOSAL: archivo del grupo no válido")
                parsed.append(ChangeProposal(**{k: item[k] for k in ChangeProposal.__dataclass_fields__}))
            batch = ChangeSet(record["id"], tuple(parsed), record["created"], record.get("source", "command"))
            return {**record, "diff": batch.diff, "batch": batch}
        if any(not isinstance(record.get(key), str) for key in ("path", "operation", "before", "after", "created", "status")):
            raise ProposalError("INVALID_PROPOSAL: campos no válidos")
        if record.get("before_sha256") is not None and not isinstance(record["before_sha256"], str):
            raise ProposalError("INVALID_PROPOSAL: hash no válido")
        proposal = ChangeProposal(**{key: record[key] for key in ChangeProposal.__dataclass_fields__})
        return {**record, "diff": proposal.diff}
