"""Policy Engine - Decides what runs where."""

from __future__ import annotations
import ast
import operator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from pathlib import Path


_MAX_CONDITION_AST_NODES = 256

_COMPARE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}

_SAFE_RESOURCE_METHODS = frozenset({"startswith", "endswith"})


def _eval_policy_condition(condition: str, context: dict, resource: str) -> bool:
    """Safely evaluate a declarative policy condition AST without dynamic code execution."""
    if not isinstance(condition, str) or not condition.strip():
        raise ValueError("Policy condition must be a non-empty string")
    tree = ast.parse(condition, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > _MAX_CONDITION_AST_NODES:
        raise ValueError("Policy condition exceeds maximum AST complexity")
    return bool(_eval_ast_node(tree.body, context, resource))


def _eval_ast_node(node: ast.AST, context: dict, resource: str) -> Any:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (bool, int, float, str)) or node.value is None:
            return node.value
        raise ValueError(f"Unsupported literal type: {type(node.value).__name__}")

    if isinstance(node, ast.Name):
        if node.id == "context":
            return context
        if node.id == "resource":
            return resource
        raise ValueError(f"Disallowed identifier in policy condition: {node.id}")

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result: Any = True
            for value in node.values:
                result = _eval_ast_node(value, context, resource)
                if not result:
                    return result
            return result
        if isinstance(node.op, ast.Or):
            result = False
            for value in node.values:
                result = _eval_ast_node(value, context, resource)
                if result:
                    return result
            return result
        raise ValueError(f"Unsupported boolean operator: {type(node.op).__name__}")

    if isinstance(node, ast.UnaryOp):
        operand = _eval_ast_node(node.operand, context, resource)
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(node.op, ast.USub) and isinstance(operand, (int, float)) and not isinstance(operand, bool):
            return -operand
        if isinstance(node.op, ast.UAdd) and isinstance(operand, (int, float)) and not isinstance(operand, bool):
            return +operand
        raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")

    if isinstance(node, ast.Compare):
        left = _eval_ast_node(node.left, context, resource)
        for op, comparator in zip(node.ops, node.comparators):
            fn = _COMPARE_OPS.get(type(op))
            if fn is None:
                raise ValueError(f"Unsupported comparison operator: {type(op).__name__}")
            right = _eval_ast_node(comparator, context, resource)
            if not fn(left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.List):
        return [_eval_ast_node(elt, context, resource) for elt in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_ast_node(elt, context, resource) for elt in node.elts)
    if isinstance(node, ast.Set):
        return {_eval_ast_node(elt, context, resource) for elt in node.elts}

    if isinstance(node, ast.Subscript):
        target = _eval_ast_node(node.value, context, resource)
        if target is not context or not isinstance(target, dict):
            raise ValueError("Subscript is only allowed on context dict")
        key = _eval_ast_node(node.slice, context, resource)
        if not isinstance(key, (str, int)):
            raise ValueError("Subscript key must be str or int")
        return target[key]

    if isinstance(node, ast.Call):
        if node.keywords:
            raise ValueError("Keyword arguments are not allowed in policy conditions")
        if not isinstance(node.func, ast.Attribute):
            raise ValueError("Direct function calls are not allowed in policy conditions")
        attr = node.func.attr
        if attr.startswith("_"):
            raise ValueError("Private/dunder attributes are not allowed in policy conditions")
        target = _eval_ast_node(node.func.value, context, resource)
        args = [_eval_ast_node(arg, context, resource) for arg in node.args]
        if target is context and isinstance(target, dict) and attr == "get":
            if not 1 <= len(args) <= 2:
                raise ValueError("context.get expects 1 or 2 arguments")
            return target.get(*args)
        if target is resource and isinstance(target, str) and attr in _SAFE_RESOURCE_METHODS:
            if not 1 <= len(args) <= 3:
                raise ValueError(f"resource.{attr} expects 1 to 3 arguments")
            return getattr(target, attr)(*args)
        raise ValueError(f"Disallowed method call in policy condition: {attr}")

    raise ValueError(f"Unsupported syntax in policy condition: {type(node).__name__}")


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
                # Safely evaluate declarative condition against context and resource
                allowed = _eval_policy_condition(rule.condition, context, resource)
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
