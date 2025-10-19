"""Utilities for generating thread-safe incrementing identifiers."""
from __future__ import annotations

import threading
from typing import Any


class IncrementingIdMixin:
    """Provide a thread-safe ``_next_id`` helper for IB client classes."""

    def __init__(self, *, initial_request_id: int = 0, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._req_id = initial_request_id
        self._id_lock = threading.Lock()

    def _next_id(self) -> int:
        with self._id_lock:
            self._req_id += 1
            return self._req_id


__all__ = ["IncrementingIdMixin"]
