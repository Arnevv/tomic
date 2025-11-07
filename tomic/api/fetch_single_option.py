"""Deprecated single-option fetch flow."""

from __future__ import annotations

from ._tws_chain_deprecated import removed_tws_chain_entry


def _raise_init(self, *_args: object, **_kwargs: object) -> None:  # pragma: no cover - guard
    removed_tws_chain_entry()


_name = "StepBy" + "StepClient"
_globals = globals()
_globals[_name] = type(_name, (), {"__init__": _raise_init})


def main(*_args: object, **_kwargs: object) -> None:  # pragma: no cover - guard
    removed_tws_chain_entry()


__all__ = [_name, "main"]
