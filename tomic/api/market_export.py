"""Deprecated module for legacy TWS market exports."""

from __future__ import annotations

from ._tws_chain_deprecated import removed_tws_chain_entry


def __getattr__(name: str):  # pragma: no cover - guard
    removed_tws_chain_entry()


__all__: list[str] = []
