"""CSV exporter for proposal data."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .utils import RunMetadata


def export_proposals_csv(
    records: Sequence[Mapping[str, Any]],
    *,
    columns: Sequence[str],
    path: str | Path,
    run_meta: RunMetadata,
) -> Path:
    """Write ``records`` to ``path`` and return the resulting :class:`Path`."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    metadata = run_meta.as_dict()
    footer_rows = []
    if run_meta.extra:
        extra_footer = run_meta.extra.get("footer_rows")
        if isinstance(extra_footer, Sequence):
            footer_rows = list(extra_footer)

    with target.open("w", newline="", encoding="utf-8") as handle:
        handle.write(f"# meta: {json.dumps(metadata, ensure_ascii=False)}\n")
        writer = csv.DictWriter(
            handle,
            fieldnames=list(columns),
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in records:
            writer.writerow({col: _normalise_cell(row.get(col)) for col in columns})
        if footer_rows:
            handle.write("\n")
            footer_writer = csv.writer(handle)
            for key, value in footer_rows:
                footer_writer.writerow([key, _format_footer_value(value)])
    return target


def _normalise_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return ""
    return value


def _format_footer_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value
