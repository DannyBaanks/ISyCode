"""Structural contracts between the ISyCode UI and its adapters.

These interfaces describe data flow only. They do not grant capabilities,
make policy decisions, or turn discovered MCP tools/skills into authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from isycode.workspace import DirectoryListing, SearchOutcome, WorkspaceRead


@dataclass(frozen=True)
class CatalogSnapshot:
    configured: bool
    items: list[dict[str, Any]]
    state: str
    detail: str = ""


@dataclass(frozen=True)
class PlanOutcome:
    plan: Any
    model: str
    provider_label: str
    host_name: str
    origin: str = "demo"


@runtime_checkable
class AgentRuntime(Protocol):
    """Planner/runtime facade; it is not an ISyCode authorization boundary."""

    async def plan(
        self,
        intent: str,
        on_chunk: Callable[[str, str], None] | None = None,
    ) -> PlanOutcome: ...

    def approval_summary(self) -> Mapping[str, Any]: ...

    def approval_context(self) -> str: ...

    async def execute(self, plan: Any, *, expected_context: str) -> Any: ...

    def verify_execution(self, execution: Any) -> Mapping[int, Any]: ...


@runtime_checkable
class WorkspaceProvider(Protocol):
    """Workspace display contract; authority is checked by native action owners."""

    @property
    def workspace_root(self) -> Path: ...

    @property
    def authority_roots(self) -> tuple[Path, ...]: ...

    def read(self, logical_path: str) -> WorkspaceRead: ...

    def list_directory(
        self, logical_path: str, *, show_ignored: bool = False
    ) -> DirectoryListing: ...

    def search(self, query: str, *, show_ignored: bool = False) -> SearchOutcome: ...


@runtime_checkable
class MCPProvider(Protocol):
    """Read-only discovery of OpenISy MCP server status."""

    def mcp_status(self) -> CatalogSnapshot: ...


@runtime_checkable
class SkillCatalog(Protocol):
    """Read-only discovery of skills available from OpenISy."""

    def skills(self) -> CatalogSnapshot: ...


@runtime_checkable
class OpenIsyCatalogProvider(MCPProvider, SkillCatalog, Protocol):
    """An adapter that exposes both read-only OpenISy catalogs."""

    def provider_auth(self) -> CatalogSnapshot: ...

    def provider_catalog(self) -> CatalogSnapshot: ...


@runtime_checkable
class ReceiptVerifier(Protocol):
    """Verifies a host receipt using its host-provided claim bundle."""

    def verify(self, receipt: Any, claim_bundle: Any) -> Any: ...


@runtime_checkable
class WorkspaceFactory(Protocol):
    def __call__(self, root: Path) -> WorkspaceProvider: ...


@runtime_checkable
class RuntimeFactory(Protocol):
    def __call__(self, workspace_root: Path) -> AgentRuntime: ...


@runtime_checkable
class OpenIsyClientFactory(Protocol):
    def __call__(self, directory: Path) -> OpenIsyCatalogProvider: ...
