"""Runtime registry."""

from __future__ import annotations
from typing import Dict
from pathlib import Path
from .base import BaseRuntime, SandboxRuntime, WASMRuntime, VMRuntime, ToolCall, ExecutionResult
from ..policy import RuntimeLayer
from .linux import LinuxCommandRuntime, installation_status


class RuntimeRegistry:
    """Manages available runtimes."""
    
    def __init__(self, working_dir: Path):
        self.working_dir = working_dir
        self._runtimes: Dict[RuntimeLayer, BaseRuntime] = {}
        self._init_runtimes()
    
    def _init_runtimes(self) -> None:
        self._runtimes[RuntimeLayer.LAYER_A] = SandboxRuntime(self.working_dir)
        self._runtimes[RuntimeLayer.LINUX_ISOLATED] = LinuxCommandRuntime(self.working_dir)
        # TODO: Initialize WASM and VM when available
        # self._runtimes[RuntimeLayer.LAYER_B] = WASMRuntime(self.working_dir)
        # self._runtimes[RuntimeLayer.LAYER_C] = VMRuntime(self.working_dir)
    
    def get(self, layer: RuntimeLayer) -> BaseRuntime:
        runtime = self._runtimes.get(layer)
        if not runtime:
            raise ValueError(f"Runtime {layer} not available")
        return runtime
    
    def get_available(self) -> list[RuntimeLayer]:
        return list(self._runtimes.keys())
    
    def is_available(self, layer: RuntimeLayer) -> bool:
        if layer == RuntimeLayer.LINUX_ISOLATED:
            return installation_status()["installed"]
        return layer in self._runtimes
