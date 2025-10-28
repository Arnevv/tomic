"""Utility helpers for executing CLI modules."""

from __future__ import annotations

import subprocess
import sys
from typing import Sequence


def _format_command(command: Sequence[str]) -> str:
    """Return a shell-ish representation of ``command`` for logging purposes."""

    def _quote(part: str) -> str:
        if " " in part or "\t" in part:
            return f'"{part}"'
        return part

    return " ".join(_quote(part) for part in command)


def run_module(module_name: str, *args: str) -> int:
    """Run a Python module using ``python -m``.

    The control panel frequently invokes helper modules as subprocesses. Some of
    those modules return a non-zero exit status to indicate domain-level
    failures (e.g. een exit-order die niet kon worden uitgevoerd).  Dat is
    waardevolle feedback, maar het hoort het hoofdmenu niet te laten crashen.

    Daarom vangen we het exitresultaat hier op: we voeren de module altijd uit,
    melden eventuele non-zero exit-codes en geven het resultaat terug aan de
    aanroeper.
    """

    command = [sys.executable, "-m", module_name, *args]
    result = subprocess.run(command, check=False)
    if result.returncode:
        cmd_str = _format_command(command)
        sys.stderr.write(
            "⚠️  Module-uitvoering mislukte"
            f" (exit-code {result.returncode}): {cmd_str}\n"
        )
    return result.returncode
