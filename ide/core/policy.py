"""Policy Engine - Decides what runs where."""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from pathlib import Path


class RuntimeLayer(str, Enum):
    LAYER_A = "layer_a"      # Python sandbox (best effort, NO security boundary)
    LAYER_B = "layer_b"      # WASM (real boundary)
    LAYER_C = "layer_c"      # Hyper-V VM (real boundary)
    LINUX_ISOLATED = "linux_isolated"  # Mandatory Linux namespaces, offline tmpfs


class ActionType(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    NETWORK = "network"
    ASK_MODEL = "ask_model"
    VERIFY = "verify"


@dataclass
class PolicyDecision:
    allowed: bool
    runtime: RuntimeLayer
    reason: str
    evidence: dict = field(default_factory=dict)
    requires_verification: bool = False


@dataclass
class PolicyRule:
    action: ActionType
    condition: str  # Python expression evaluated with context
    runtime: RuntimeLayer
    allowed: bool = True
    reason: str = ""
    requires_verification: bool = False


DEFAULT_RULES = [
    # Network access - always deny by default
    PolicyRule(
        action=ActionType.NETWORK,
        condition="True",
        runtime=RuntimeLayer.LAYER_A,
        allowed=False,
        reason="Network access denied by default"
    ),
    PolicyRule(
        action=ActionType.EXECUTE,
        condition="context.get('isolated_linux', False)",
        runtime=RuntimeLayer.LINUX_ISOLATED,
        allowed=True,
        reason="Command requires the mandatory offline Linux profile and operator authorization"
    ),
    # Execute untrusted code - requires WASM or VM
    PolicyRule(
        action=ActionType.EXECUTE,
        condition="not context.get('trusted', False)",
        runtime=RuntimeLayer.LAYER_B,
        allowed=True,
        reason="Untrusted code requires WASM boundary"
    ),
    # Execute trusted code - can run in Layer A
    PolicyRule(
        action=ActionType.EXECUTE,
        condition="context.get('trusted', False)",
        runtime=RuntimeLayer.LAYER_A,
        allowed=True,
        reason="Trusted code allowed in sandbox"
    ),
    # Write to workspace - allowed in Layer A with verification
    PolicyRule(
        action=ActionType.WRITE,
        condition="True",
        runtime=RuntimeLayer.LAYER_A,
        allowed=True,
        reason="File writes allowed in sandbox",
        requires_verification=True
    ),
    # Read - allowed in Layer A
    PolicyRule(
        action=ActionType.READ,
        condition="True",
        runtime=RuntimeLayer.LAYER_A,
        allowed=True,
        reason="File reads allowed in sandbox"
    ),
    # Verify - runs in Layer A
    PolicyRule(
        action=ActionType.VERIFY,
        condition="True",
        runtime=RuntimeLayer.LAYER_A,
        allowed=True,
        reason="Verification runs in sandbox",
        requires_verification=True
    ),
]


class PolicyEngine:
    """
    The model proposes, the policy decides.
    The LLM NEVER decides the security boundary.
    """
    
    def __init__(self, rules: list[PolicyRule] = None):
        self.rules = rules or DEFAULT_RULES
    
    def evaluate(self, action: str, resource: str, context: dict) -> PolicyDecision:
        """
        Model proposes: 'I want to execute python test.py'
        Policy decides: ALLOW/DENY with specific runtime
        """
        try:
            action_type = ActionType(action.lower())
        except ValueError:
            action_type = ActionType.EXECUTE
        
        # Evaluate rules in order
        for rule in self.rules:
            if rule.action != action_type:
                continue
            
            try:
                # Evaluate condition with context
                allowed = eval(rule.condition, {"__builtins__": {}}, {"context": context, "resource": resource})
                if allowed:
                    return PolicyDecision(
                        allowed=rule.allowed,
                        runtime=rule.runtime,
                        reason=rule.reason or f"Matched rule: {rule.condition}",
                        requires_verification=rule.requires_verification
                    )
            except Exception:
                continue
        
        # Default deny
        return PolicyDecision(
            allowed=False,
            runtime=RuntimeLayer.LAYER_A,
            reason=f"No matching rule for {action} on {resource}",
            requires_verification=False
        )
    
    def add_rule(self, rule: PolicyRule) -> None:
        self.rules.insert(0, rule)
    
    def get_rules_summary(self) -> list[dict]:
        return [
            {
                "action": r.action.value,
                "condition": r.condition,
                "runtime": r.runtime.value,
                "allowed": r.allowed,
                "reason": r.reason,
                "requires_verification": r.requires_verification
            }
            for r in self.rules
        ]
