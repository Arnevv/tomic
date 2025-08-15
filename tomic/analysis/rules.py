"""Simple rule evaluation for alerts and proposals."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

ALLOWED_GLOBALS = {"abs": abs, "min": min, "max": max, "round": round}


def _eval_condition(condition: str, context: Dict[str, Any]) -> bool:
    """Safely evaluate ``condition`` in ``context``.

    The evaluation environment exposes a very small set of safe built-ins.
    Any error during evaluation results in ``False``.
    """

    try:
        return bool(eval(condition, {"__builtins__": {}}, {**ALLOWED_GLOBALS, **context}))
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
