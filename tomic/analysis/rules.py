"""Simple rule evaluation for alerts and proposals."""
from __future__ import annotations

import ast
import operator
from typing import Any, Dict, Iterable, List

# Safe operators for expression evaluation
_SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.And: lambda a, b: a and b,
    ast.Or: lambda a, b: a or b,
    ast.Not: operator.not_,
}

# Safe functions allowed in expressions
_SAFE_FUNCTIONS = {"abs": abs, "min": min, "max": max, "round": round}


def _safe_eval_node(node: ast.AST, context: Dict[str, Any]) -> Any:
    """Recursively evaluate an AST node with restricted operations."""
    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body, context)
    elif isinstance(node, ast.Constant):
        return node.value
    elif isinstance(node, ast.Num):  # Python 3.7 compatibility
        return node.n
    elif isinstance(node, ast.Str):  # Python 3.7 compatibility
        return node.s
    elif isinstance(node, ast.Name):
        name = node.id
        if name in context:
            return context[name]
        if name in _SAFE_FUNCTIONS:
            return _SAFE_FUNCTIONS[name]
        if name in ("True", "False", "None"):
            return {"True": True, "False": False, "None": None}[name]
        return None  # Unknown names resolve to None
    elif isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPERATORS:
            raise ValueError(f"Unsafe operator: {op_type.__name__}")
        left = _safe_eval_node(node.left, context)
        right = _safe_eval_node(node.right, context)
        if left is None or right is None:
            return None
        return _SAFE_OPERATORS[op_type](left, right)
    elif isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPERATORS:
            raise ValueError(f"Unsafe operator: {op_type.__name__}")
        operand = _safe_eval_node(node.operand, context)
        if operand is None:
            return None
        return _SAFE_OPERATORS[op_type](operand)
    elif isinstance(node, ast.Compare):
        left = _safe_eval_node(node.left, context)
        for op, comparator in zip(node.ops, node.comparators):
            op_type = type(op)
            if op_type not in _SAFE_OPERATORS:
                raise ValueError(f"Unsafe operator: {op_type.__name__}")
            right = _safe_eval_node(comparator, context)
            if left is None or right is None:
                return False
            if not _SAFE_OPERATORS[op_type](left, right):
                return False
            left = right
        return True
    elif isinstance(node, ast.BoolOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPERATORS:
            raise ValueError(f"Unsafe operator: {op_type.__name__}")
        values = [_safe_eval_node(v, context) for v in node.values]
        if op_type == ast.And:
            return all(values)
        else:  # ast.Or
            return any(values)
    elif isinstance(node, ast.Call):
        func = _safe_eval_node(node.func, context)
        if func not in _SAFE_FUNCTIONS.values():
            raise ValueError(f"Unsafe function call")
        args = [_safe_eval_node(arg, context) for arg in node.args]
        if any(a is None for a in args):
            return None
        return func(*args)
    elif isinstance(node, ast.IfExp):
        test = _safe_eval_node(node.test, context)
        if test:
            return _safe_eval_node(node.body, context)
        return _safe_eval_node(node.orelse, context)
    else:
        raise ValueError(f"Unsafe AST node type: {type(node).__name__}")


def _eval_condition(condition: str, context: Dict[str, Any]) -> bool:
    """Safely evaluate ``condition`` in ``context``.

    Uses AST parsing to only allow safe operations (comparisons, arithmetic,
    boolean logic, and a small set of safe functions). This prevents code
    injection attacks that would be possible with eval().

    Any error during evaluation results in ``False``.
    """
    try:
        tree = ast.parse(condition, mode="eval")
        result = _safe_eval_node(tree, context)
        return bool(result) if result is not None else False
    except Exception:
        return False


def evaluate_rules(rules: Iterable[Dict[str, str]], context: Dict[str, Any]) -> List[str]:
    """Evaluate declarative ``rules`` against ``context`` and return messages.

    Each rule in ``rules`` must be a mapping with ``condition`` and ``message``
    keys.  The ``condition`` is evaluated as a Python expression using values
    from ``context``.  When the expression is truthy the formatted ``message``
    is appended to the result list.  Unknown variables resolve to ``None`` and
    formatting errors are ignored, so poorly defined rules will simply produce
    no output rather than crashing the application.
    """

    alerts: List[str] = []
    for rule in rules:
        cond = rule.get("condition")
        msg = rule.get("message")
        if not cond or not msg:
            continue
        if _eval_condition(cond, context):
            try:
                alerts.append(msg.format(**context))
            except Exception:
                alerts.append(msg)
    return alerts


__all__ = ["evaluate_rules"]
