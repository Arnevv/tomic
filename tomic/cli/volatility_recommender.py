"""Recommend option strategies based on volatility metrics."""

from __future__ import annotations

import ast
import operator
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def _load_rules(path: Path | None = None) -> List[Dict[str, Any]]:
    if path is None:
        path = Path(__file__).resolve().parent.parent / "volatility_rules.yaml"
    if not path.exists():
        return []
    try:
        import yaml  # type: ignore
    except Exception:  # pragma: no cover - PyYAML optional
        data = []
        current: Dict[str, Any] | None = None
        list_key: str | None = None
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            if line.startswith("- "):
                if current:
                    data.append(current)
                current = {}
                line = line[2:]
            if current is None:
                continue
            if line.lstrip().startswith("- ") and list_key:
                current.setdefault(list_key, []).append(
                    line.lstrip()[2:].strip().strip('"')
                )
                continue
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                if not val:
                    list_key = key
                    current[list_key] = []
                else:
                    list_key = None
                    val = val.strip('"')
                    low = val.lower()
                    if low in {"true", "false"}:
                        current[key] = low == "true"
                    elif low in {"null", "none"}:
                        current[key] = None
                    elif val.startswith("[") and val.endswith("]"):
                        items = [
                            v.strip().strip('"')
                            for v in val[1:-1].split(",")
                            if v.strip()
                        ]
                        current[key] = items
                    else:
                        try:
                            if "." in val:
                                current[key] = float(val)
                            else:
                                current[key] = int(val)
                        except ValueError:
                            current[key] = val
        if current:
            data.append(current)
        return data
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    rules: List[Dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict):
            rules.append(item)
    return rules


_RULES = _load_rules()

_RANGE_RE = re.compile(r"^(\w+)\s+(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)$")

# Safe operators for expression evaluation
_SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.And: lambda a, b: a and b,
    ast.Or: lambda a, b: a or b,
    ast.Not: operator.not_,
    ast.USub: operator.neg,
}


def _safe_eval_node(node: ast.AST, context: Dict[str, Any]) -> Any:
    """Recursively evaluate an AST node with restricted operations."""
    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body, context)
    elif isinstance(node, ast.Constant):
        return node.value
    elif isinstance(node, ast.Num):  # Python 3.7 compatibility
        return node.n
    elif isinstance(node, ast.Name):
        name = node.id
        if name in context:
            return context[name]
        if name in ("True", "False", "None"):
            return {"True": True, "False": False, "None": None}[name]
        return None
    elif isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPERATORS:
            return None
        left = _safe_eval_node(node.left, context)
        right = _safe_eval_node(node.right, context)
        if left is None or right is None:
            return None
        return _SAFE_OPERATORS[op_type](left, right)
    elif isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPERATORS:
            return None
        operand = _safe_eval_node(node.operand, context)
        if operand is None:
            return None
        return _SAFE_OPERATORS[op_type](operand)
    elif isinstance(node, ast.Compare):
        left = _safe_eval_node(node.left, context)
        for op, comparator in zip(node.ops, node.comparators):
            op_type = type(op)
            if op_type not in _SAFE_OPERATORS:
                return False
            right = _safe_eval_node(comparator, context)
            if left is None or right is None:
                return False
            if not _SAFE_OPERATORS[op_type](left, right):
                return False
            left = right
        return True
    elif isinstance(node, ast.BoolOp):
        op_type = type(node.op)
        values = [_safe_eval_node(v, context) for v in node.values]
        if op_type == ast.And:
            return all(values)
        return any(values)
    else:
        return None


def _check_expr(expr: str, metrics: Dict[str, Any]) -> bool:
    """Safely evaluate expression against metrics.

    Supports:
    - Range expressions like "iv_rank 0.3-0.7"
    - Comparison expressions like "iv_rank > 0.5"
    - Boolean expressions like "iv_rank > 0.3 and hv < 30"

    Uses AST parsing to prevent code injection attacks.
    """
    expr = expr.strip()
    m = _RANGE_RE.match(expr)
    if m:
        var = m.group(1)
        lo = float(m.group(2))
        hi = float(m.group(3))
        val = metrics.get(var)
        if val is None:
            return False
        try:
            return lo <= float(val) <= hi
        except Exception:
            return False
    try:
        tree = ast.parse(expr, mode="eval")
        result = _safe_eval_node(tree, metrics)
        return bool(result) if result is not None else False
    except Exception:
        return False


def recommend_strategy(
    metrics: Dict[str, Any], rules: List[Dict[str, Any]] | None = None
) -> Optional[Dict[str, Any]]:
    """Return first matching strategy rule for given metrics."""
    matches = recommend_strategies(metrics, rules)
    return matches[0] if matches else None


def recommend_strategies(
    metrics: Dict[str, Any], rules: List[Dict[str, Any]] | None = None
) -> List[Dict[str, Any]]:
    """Return all matching strategy rules for given metrics."""
    if rules is None:
        rules = _RULES
    matched: List[Dict[str, Any]] = []
    for rule in rules:
        crit = rule.get("criteria", [])
        if all(_check_expr(c, metrics) for c in crit):
            matched.append(rule)
    return matched


__all__ = ["recommend_strategy", "recommend_strategies", "_load_rules"]
