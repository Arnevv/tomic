"""Shared tabulate helper with a lightweight fallback implementation."""
from __future__ import annotations

from typing import Iterable, Sequence

try:  # pragma: no cover - optional dependency
    from tabulate import tabulate as _real_tabulate
except Exception:  # pragma: no cover - fallback when tabulate is missing

    def _tabulate(
        rows: Iterable[Sequence[object]],
        headers: Sequence[object] | None = None,
        tablefmt: str = "simple",
    ) -> str:
        table_rows: list[Sequence[object]] = list(rows)
        if headers:
            table_rows = [headers, *table_rows]
        if not table_rows:
            return ""
        widths = [max(len(str(cell)) for cell in column) for column in zip(*table_rows)]

        def _fmt(row: Sequence[object]) -> str:
            return "| " + " | ".join(str(cell).ljust(widths[idx]) for idx, cell in enumerate(row)) + " |"

        lines: list[str] = []
        if headers:
            lines.append(_fmt(headers))
            separator = "|-" + "-|-".join("-" * widths[idx] for idx in range(len(widths))) + "-|"
            lines.append(separator)
        for row in rows:
            lines.append(_fmt(row))
        return "\n".join(lines)
else:  # pragma: no cover - passthrough when tabulate available

    def _tabulate(
        rows: Iterable[Sequence[object]],
        headers: Sequence[object] | None = None,
        tablefmt: str = "simple",
    ) -> str:
        return _real_tabulate(rows, headers=headers, tablefmt=tablefmt)


__all__ = ["tabulate"]

tabulate = _tabulate
