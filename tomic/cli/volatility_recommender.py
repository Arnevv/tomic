"""Recommend option strategies based on volatility metrics."""

from __future__ import annotations

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


def _check_expr(expr: str, metrics: Dict[str, Any]) -> bool:
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
        return bool(eval(expr, {}, metrics))
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
