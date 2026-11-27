"""Host authority shared by agent transports and explicit editor actions."""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

from core.policy import RuntimeLayer
from core.proposals import ProposalError, ProposalService
from core.resident import ResidentReader, SelfScanner
from core.runtime.base import ExecutionResult, ToolCall
from core.tool_settings import ToolSettings
from core.command_grants import GrantStore
from core.runtime.linux import CommandError
from core.isycode_tools import (
    MUTATING_ISYCODE_TOOLS,
    READONLY_ISYCODE_TOOLS,
    execute_isycode_mcp_tool,
    execute_isycode_mutating_tool,
    execute_isycode_readonly_tool,
    preview_isycode_mutating_tool,
)


class ToolExecutionService:
    def __init__(self, workspace, policy, runtimes):
        self.workspace = Path(workspace).resolve()
        self.policy = policy
        self.runtimes = runtimes
        self.settings = ToolSettings(self.workspace)
        self.proposals = ProposalService(self.workspace)
        self.on_event = None
        self._event_error = False
        self.grants = GrantStore(self.workspace)

    def _emit(self, kind, **metadata):
        if self.on_event is not None:
            try:
                self.on_event({"type": kind, **metadata})
            except Exception:
                # An event failure cannot turn an applied receipt into 'failed'.
                self._event_error = True

    def _deny(self, code, message, **evidence):
        return ExecutionResult(False, stderr=message, returncode=1,
                               error_code=code, evidence=evidence)

    def _gate(self, name, arguments, mode, actor, plan):
        if actor == "AGENT":
            if mode not in {"plan", "coder"}:
                return self._deny("INVALID_MODE", "El modo del agente no es válido.")
            if mode == "plan" and name in ({"write", "edit", "python", "run_command"} | MUTATING_ISYCODE_TOOLS):
                return self._deny("PLAN_MODE_WRITE_DENIED", "PLAN permite inspeccionar y proponer; cambia a CODER para aplicar.")
        if not self.settings.available(name):
            return self._deny("UNAVAILABLE_TOOL", "Esta herramienta no tiene un runtime habilitado.")
        if actor == "AGENT" and not self.settings.enabled(name):
            return self._deny("TOOL_DISABLED", "La herramienta está desactivada en este proyecto.")
        if actor == "AGENT" and name in {"write", "edit"}:
            path = self.proposals._path(arguments.get("path"))
            relative = str(path.relative_to(self.workspace))
            restricted = set()
            for item in ResidentReader(self.workspace).map_records():
                if item.get("modify") == "restricted":
                    try:
                        restricted.add(str(self.proposals._path(item.get("path")).relative_to(self.workspace)))
                    except ProposalError:
                        continue
            if relative in restricted:
                records = (plan or {}).get("records", [])
                approved = any(r.get("type") == "approval" and r.get("status") == "approved" for r in records)
                targeted = any(r.get("type") == "modify" and r.get("path") == relative for r in records)
                if not (approved and targeted):
                    return self._deny("PROTECTED_ZONE_REQUIRES_APPROVAL", "Esta ruta requiere un plan aprobado que la incluya.")
        action = {"write": "write", "edit": "write", "verify": "verify", "run_command": "execute",
                  "isycode_mkdir": "write", "isycode_rmdir": "write", "isycode_move_file": "write", "isycode_delete_file": "write",
                  "isycode_mcp_execute": "write"}.get(name, "read")
        decision = self.policy.evaluate(action, name, {"tool": name, "args": arguments,
                                                      "trusted": name != "run_command", "isolated_linux": name == "run_command",
                                                      "mode": mode, "actor": actor})
        if not decision.allowed:
            return self._deny("POLICY_DENIED", "La política del host rechazó esta acción.", reason=decision.reason)
        if not self.runtimes.is_available(decision.runtime):
            return self._deny("UNAVAILABLE_RUNTIME", "El runtime solicitado por la política no está disponible.")
        if name == "run_command" and decision.runtime != RuntimeLayer.LINUX_ISOLATED:
            return self._deny("ISOLATION_REQUIRED", "Los comandos no pueden usar un runtime del host ni Layer A.")
        if name in {"write", "edit", "resident_query", "resident_scan"} and decision.runtime != RuntimeLayer.LAYER_A:
            return self._deny("UNAVAILABLE_RUNTIME", "Este adaptador de archivos/residente solo implementa Layer A.")
        return decision

    async def _command(self, arguments, call_id, mode, actor, plan, approve, decision):
        runtime = self.runtimes.get(decision.runtime)
        request = runtime.prepare(arguments)
        previous_grant = self.grants.allowed(request.identity)
        answer = True if previous_grant else None
        if not previous_grant:
            if approve is None:
                return self._deny("APPROVAL_REQUIRED", "El comando necesita una decisión del operador.")
            preview = ToolCall("run_command", copy.deepcopy(arguments), call_id)
            preview.approval_kind = "command"
            preview.command_identity = request.identity
            preview.prepared_diff = (f"argv: {json.dumps(list(request.identity.argv), ensure_ascii=False)}\n"
                                     f"cwd: {request.identity.cwd}\nEjecutable: {request.identity.executable}\n"
                                     f"SHA-256: {request.identity.executable_sha256}\nPerfil: Linux sin red · copia en tmpfs\n"
                                     f"Máximo: {request.timeout} s\nLos cambios de archivos requieren otra aprobación.")
            answer = await approve(preview)
            if answer is not True and answer != "always":
                self._emit("command_decided", command_key=request.identity.key, status="rejected")
                return self._deny("USER_REJECTED", "El comando fue rechazado.")
        decision = self._gate("run_command", arguments, mode, actor, plan)
        if isinstance(decision, ExecutionResult):
            return decision
        await runtime.check_capabilities(request)
        decision = self._gate("run_command", arguments, mode, actor, plan)
        if isinstance(decision, ExecutionResult):
            return decision
        if previous_grant and not self.grants.allowed(request.identity):
            return self._deny("GRANT_REVOKED", "El permiso fue revocado antes de ejecutar.")
        current = runtime.prepare(arguments)
        if current.identity != request.identity:
            return self._deny("COMMAND_IDENTITY_CHANGED", "Cambió el ejecutable o el perfil después de revisar.")
        if answer == "always":
            self.grants.allow(request.identity)
        approval = "permanent" if previous_grant or answer == "always" else "once"
        self._emit("command_decided", command_key=request.identity.key, status="approved", scope=approval)
        def authorize():
            current_gate = self._gate("run_command", arguments, mode, actor, plan)
            return (not isinstance(current_gate, ExecutionResult)
                    and (approval == "once" or self.grants.allowed(request.identity)))
        report = await runtime.run_request(request, authorize=authorize)
        evidence = {"command": {"request": request.id, "argv": list(request.identity.argv), "cwd": request.identity.cwd,
                                 "executable_sha256": request.identity.executable_sha256,
                                 "profile": report["profile"], "profile_sha256": report["profile_sha256"],
                                 "returncode": report["returncode"], "approval": approval, "original_checkout_writable": False}}
        result = ExecutionResult(report["returncode"] == 0, stdout=report["stdout"], stderr=report["stderr"],
                                 returncode=report["returncode"], evidence=evidence)
        if report["unsupported"]:
            result.success = False
            result.error_code = "UNSUPPORTED_COMMAND_CHANGES"
            result.stderr += "\nCambios no soportados en la copia; nada se aplica: " + ", ".join(report["unsupported"])[:2000]
            return result
        if not result.success or not report["changes"]:
            return result
        for path in report["changes"]:
            gate = self._gate("write", {"path": path}, mode, actor, plan)
            if isinstance(gate, ExecutionResult):
                return gate
        batch = self.proposals.prepare_batch(report["changes"], expected_bases=report["bases"], source="command:" + request.id)
        result.evidence["changeset"] = {"id": batch.id, "status": "pending", "paths": [change.path for change in batch.changes]}
        self._emit("proposal_prepared", proposal_id=batch.id, paths=result.evidence["changeset"]["paths"], call_id=call_id)
        if approve is None:
            result.success = False
            result.error_code = "APPROVAL_REQUIRED"
            result.stderr += "\nLos cambios de la copia esperan revisión."
            return result
        preview = ToolCall("apply_changes", {"paths": [change.path for change in batch.changes]}, call_id)
        preview.proposal_id = batch.id
        preview.prepared_diff = batch.diff
        try:
            approved = await approve(preview)
        except asyncio.CancelledError:
            self.proposals.mark_batch(batch, "cancelled")
            self._emit("proposal_decided", proposal_id=batch.id, status="cancelled")
            raise
        if approved is not True:
            self.proposals.reject_batch(batch)
            result.success = False
            result.error_code = "USER_REJECTED"
            result.evidence["changeset"]["status"] = "rejected"
            result.stderr += "\nSe rechazaron los cambios; la carpeta original se conserva."
            self._emit("proposal_decided", proposal_id=batch.id, status="rejected")
            return result
        for path in report["changes"]:
            gate = self._gate("write", {"path": path}, mode, actor, plan)
            if isinstance(gate, ExecutionResult):
                self.proposals.mark_batch(batch, "blocked")
                self._emit("proposal_decided", proposal_id=batch.id, status="blocked")
                return gate
        gate = self._gate("run_command", arguments, mode, actor, plan)
        if isinstance(gate, ExecutionResult):
            self.proposals.mark_batch(batch, "blocked")
            self._emit("proposal_decided", proposal_id=batch.id, status="blocked")
            return gate
        try:
            receipt = self.proposals.apply_batch(batch)
        except BaseException:
            self._emit("proposal_decided", proposal_id=batch.id, status=self.proposals.inspect(batch.id)["status"])
            raise
        result.evidence["changeset"].update(status="applied", receipt=receipt)
        self._emit("proposal_decided", proposal_id=batch.id, status="applied")
        return result

    async def execute(self, call, *, mode="plan", actor="AGENT", plan=None, approve=None):
        self._event_error = False
        if actor not in {"AGENT", "HOST"}:
            return self._deny("INVALID_ACTOR", "Actor no válido.")
        if not isinstance(call.name, str) or not isinstance(call.arguments, dict):
            return self._deny("INVALID_ARGUMENTS", "La herramienta requiere nombre y argumentos estructurados.")
        # The callback receives another copy; changing its arguments grants no authority.
        name, arguments, call_id = call.name, copy.deepcopy(call.arguments), str(call.id)
        proposal = None
        try:
            decision = self._gate(name, arguments, mode, actor, plan)
            if isinstance(decision, ExecutionResult):
                return decision
            self._emit("tool_started", tool=name, call_id=call_id)
            if name == "run_command":
                result = await self._command(arguments, call_id, mode, actor, plan, approve, decision)
            elif name in {"write", "edit"}:
                proposal = self.proposals.prepare(name, arguments)
                self._emit("proposal_prepared", proposal_id=proposal.id, paths=[proposal.path], call_id=call_id)
                if actor == "HOST" and "_expected_sha256" in arguments and arguments["_expected_sha256"] != proposal.before_sha256:
                    self.proposals.mark(proposal, "stale")
                    return self._deny("STALE_EDITOR", "El archivo cambió en disco. Vuelve a abrirlo antes de guardar.")
                if actor == "AGENT":
                    if approve is None:
                        return self._deny("APPROVAL_REQUIRED", "La propuesta espera aprobación del operador.", proposal_id=proposal.id)
                    preview = ToolCall(name, copy.deepcopy(arguments), call_id)
                    preview.proposal_id = proposal.id
                    preview.prepared_diff = proposal.diff
                    preview.before_sha256 = proposal.before_sha256
                    answer = await approve(preview)
                    if answer is not True:
                        self.proposals.reject(proposal)
                        self._emit("proposal_decided", proposal_id=proposal.id, status="rejected")
                        return self._deny("USER_REJECTED", "El operador rechazó la propuesta.", proposal_id=proposal.id)
                # Re-evaluate switches and policy after the asynchronous approval wait.
                decision = self._gate(name, arguments, mode, actor, plan)
                if isinstance(decision, ExecutionResult):
                    self.proposals.mark(proposal, "blocked")
                    self._emit("proposal_decided", proposal_id=proposal.id, status="blocked")
                    return decision
                receipt = self.proposals.apply(proposal)
                self._emit("proposal_decided", proposal_id=proposal.id, status="applied")
                result = ExecutionResult(True, stdout=f"Cambio aplicado: {proposal.path}",
                                         evidence={"proposal": receipt, "approval": "once" if actor == "AGENT" else "explicit_editor_save"})
            elif name == "resident_query":
                guidance = ResidentReader(self.workspace).query(str(arguments.get("intent", "")),
                                                               category=str(arguments.get("category", "general")))
                result = ExecutionResult(True, stdout=json.dumps(guidance, ensure_ascii=False))
            elif name == "resident_scan":
                result = ExecutionResult(True, stdout=json.dumps(SelfScanner(self.workspace).scan(), ensure_ascii=False))
            elif name in READONLY_ISYCODE_TOOLS:
                needs_discover_approval = (
                    actor == "AGENT"
                    and (
                        name == "isycode_mcp_discover"
                        or (name == "isycode_motor" and str(arguments.get("motor", "")).strip().lower() == "hub_route")
                    )
                )
                if needs_discover_approval:
                    if approve is None:
                        return self._deny(
                            "APPROVAL_REQUIRED",
                            "Descubrir herramientas en ISyMCP Hub consume tokens y requiere aprobación del operador.",
                        )
                    preview = ToolCall(name, copy.deepcopy(arguments), call_id)
                    q = arguments.get("query") or "(todos los servidores)"
                    srv = arguments.get("server") or "(sin filtro de servidor)"
                    preview.prepared_diff = (
                        f"Consulta de catálogo en ISyMCP Hub (consume tokens de contexto):\n"
                        f"  tool:   {name}\n"
                        f"  server: {srv}\n"
                        f"  query:  {q}\n"
                        f"  limit:  {arguments.get('limit', 12)}"
                    )
                    answer = await approve(preview)
                    if answer is not True:
                        return self._deny("USER_REJECTED", "El operador rechazó ejecutar discover en ISyMCP Hub.")
                result = await execute_isycode_readonly_tool(self.workspace, name, arguments)
            elif name in MUTATING_ISYCODE_TOOLS:
                diff_preview = preview_isycode_mutating_tool(self.workspace, name, arguments)
                if actor == "AGENT":
                    if approve is None:
                        return self._deny("APPROVAL_REQUIRED", "Esta operación de archivo requiere aprobación del operador.")
                    preview = ToolCall(name, copy.deepcopy(arguments), call_id)
                    preview.prepared_diff = diff_preview
                    answer = await approve(preview)
                    if answer is not True:
                        return self._deny("USER_REJECTED", "El operador rechazó la operación.")
                decision = self._gate(name, arguments, mode, actor, plan)
                if isinstance(decision, ExecutionResult):
                    return decision
                if name == "isycode_mcp_execute":
                    result = await execute_isycode_mcp_tool(self.workspace, arguments)
                else:
                    result = execute_isycode_mutating_tool(self.workspace, name, arguments)
            else:
                result = await self.runtimes.get(decision.runtime).execute(ToolCall(name, arguments, call_id))
            result.evidence = {**(result.evidence or {}), "actor": actor,
                               "policy": {"allowed": True, "mode": mode, "tool": name,
                                          "runtime": decision.runtime.value, "reason": decision.reason},
                               "verification": {"status": "NOT_DEMONSTRATED", "reason": "Execution success is not proof of correctness."}}
            self._emit("tool_finished", tool=name, call_id=call_id, success=result.success, error_code=result.error_code,
                       proposal_id=(result.evidence.get("changeset") or result.evidence.get("proposal") or {}).get("id", ""))
            result.evidence["events"] = "not_recorded" if self._event_error else "recorded" if self.on_event else "not_attached"
            return result
        except asyncio.CancelledError:
            if proposal is not None:
                self.proposals.mark(proposal, "cancelled")
                self._emit("proposal_decided", proposal_id=proposal.id, status="cancelled")
            self._emit("tool_finished", tool=name, call_id=call_id, success=False, error_code="CANCELLED")
            raise
        except (ValueError, OSError) as exc:
            if proposal is not None and not isinstance(exc, ProposalError):
                self.proposals.mark(proposal, "failed")
            code = str(exc).split(":", 1)[0] if isinstance(exc, (ProposalError, CommandError)) else "TOOL_STATE_ERROR"
            message = str(exc) if isinstance(exc, (ProposalError, CommandError)) else "No se pudo completar la operación. Revisa las rutas y el estado del proyecto."
            self._emit("tool_finished", tool=name, call_id=call_id, success=False, error_code=code)
            return self._deny(code, message)

    def apply_host_batch(self, batch, *, operator_approved=False, mode="plan"):
        if operator_approved is not True:
            return self._deny("APPROVAL_REQUIRED", "Revisa la recuperación antes de aplicar.")
        try:
            for change in batch.changes:
                decision = self._gate("write", {"path": change.path}, mode, "HOST", None)
                if isinstance(decision, ExecutionResult):
                    self.proposals.mark_batch(batch, "blocked")
                    return decision
            return ExecutionResult(True, evidence={"changeset": self.proposals.apply_batch(batch)})
        except (ValueError, OSError):
            return self._deny("RECOVERY_FAILED", "La recuperación no terminó. Revisa el journal y las bases; se conserva el estado parcial.")
