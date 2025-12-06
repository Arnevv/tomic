"""Timer and retry management for IB market data requests.

This module provides a mixin class that handles timeouts and retries for
asynchronous IB API requests. It is extracted from OptionChainClientLegacy
to improve code organization.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Protocol, Set

from tomic.config import get as cfg_get
from tomic.logutils import logger

if TYPE_CHECKING:
    from collections.abc import Callable


class HasMarketData(Protocol):
    """Protocol for classes that have market_data and related attributes."""

    market_data: dict[int, dict[str, Any]]
    invalid_contracts: set[int]
    data_lock: threading.RLock
    expected_contracts: int
    all_data_event: threading.Event
    use_hist_iv: bool

    def cancelMktData(self, reqId: int) -> None: ...
    def retry_incomplete_requests(
        self, ids: list[int] | None = None, *, wait: bool = True, use_new_id: bool = False
    ) -> bool: ...


class RequestTimerManager:
    """Mixin for managing request timeouts and retries.

    This mixin provides functionality to:
    - Track completed requests
    - Schedule and cancel invalidation timers
    - Retry incomplete requests with configurable retry counts
    - Manage a global timeout for all market data requests

    Attributes
    ----------
    _completed_requests : set[int]
        IDs of requests that have completed (success or failure)
    _invalid_timers : dict[int, threading.Timer]
        Active timers for request invalidation
    _request_retries : dict[int, int]
        Remaining retry counts per request ID
    _max_data_timer : threading.Timer | None
        Global timeout timer for all market data
    _retry_rounds : int
        Default number of retries per request
    """

    def __init__(self) -> None:
        """Initialize timer manager state."""
        self._completed_requests: Set[int] = set()
        self._invalid_timers: dict[int, threading.Timer] = {}
        self._request_retries: dict[int, int] = {}
        self._max_data_timer: threading.Timer | None = None
        self._retry_rounds = int(cfg_get("OPTION_DATA_RETRIES", 0))

    def _mark_complete(self: "HasMarketData", req_id: int) -> None:
        """Record completion of a contract request and set ``all_data_event`` when done.

        Parameters
        ----------
        req_id:
            The request ID to mark as complete
        """
        with self.data_lock:
            if req_id in self._completed_requests:
                return
            # Cancel streaming market data since generic ticks cannot be
            # requested as snapshots.
            try:
                self.cancelMktData(req_id)
            except Exception:
                pass
            self._request_retries.pop(req_id, None)
            self._completed_requests.add(req_id)
            if (
                self.expected_contracts
                and len(self._completed_requests) >= self.expected_contracts
            ):
                self.all_data_event.set()
                self._stop_max_data_timer()

    def _invalidate_request(self: "HasMarketData", req_id: int) -> None:
        """Mark request ``req_id`` as invalid and cancel streaming data.

        Parameters
        ----------
        req_id:
            The request ID to invalidate
        """
        with self.data_lock:
            self._invalid_timers.pop(req_id, None)
            self.invalid_contracts.add(req_id)
            rec = self.market_data.get(req_id, {})
            rec["status"] = "timeout"
            evt = rec.get("event")
        if isinstance(evt, threading.Event) and not evt.is_set():
            evt.set()
        self._mark_complete(req_id)

    def _retry_or_invalidate(self: "HasMarketData", req_id: int) -> None:
        """Retry a request when retries remain; otherwise invalidate it.

        Parameters
        ----------
        req_id:
            The request ID to retry or invalidate
        """
        retries = self._request_retries.get(req_id, 0)
        if retries > 0:
            self._request_retries[req_id] = retries - 1
            # Use a new request id when retrying to avoid ``duplicate ticker id``
            # errors that may occur if the previous id is reused too quickly.
            self.retry_incomplete_requests([req_id], wait=False, use_new_id=True)
        else:
            self._invalidate_request(req_id)

    def _cancel_invalid_timer(self, req_id: int) -> None:
        """Cancel the invalidation timer for a request.

        Parameters
        ----------
        req_id:
            The request ID whose timer should be cancelled
        """
        # Note: Uses self.data_lock from the mixin target
        with getattr(self, "data_lock", threading.RLock()):
            timer = self._invalid_timers.pop(req_id, None)
            if timer is not None:
                timer.cancel()
            self._request_retries.pop(req_id, None)

    def _schedule_invalid_timer(self: "HasMarketData", req_id: int) -> None:
        """Schedule an invalidation timer for a request.

        The timer will fire after ``BID_ASK_TIMEOUT`` seconds and either
        retry the request or mark it as invalid.

        Parameters
        ----------
        req_id:
            The request ID to schedule a timer for
        """
        timeout = cfg_get("BID_ASK_TIMEOUT", 5)
        if timeout <= 0:
            self._retry_or_invalidate(req_id)
            return
        timer = threading.Timer(timeout, self._retry_or_invalidate, args=[req_id])
        timer.daemon = True
        with self.data_lock:
            if req_id in self._invalid_timers:
                return
            self._invalid_timers[req_id] = timer
            self._request_retries.setdefault(req_id, self._retry_rounds)
            timer.start()

    def incomplete_requests(self: "HasMarketData") -> list[int]:
        """Return request IDs missing essential market data.

        Returns
        -------
        list[int]
            List of request IDs that are incomplete
        """
        if self.use_hist_iv:
            required = ["iv", "close"]
        else:
            required = ["bid", "ask", "iv", "delta", "gamma", "vega", "theta"]
        with self.data_lock:
            return [
                rid
                for rid, rec in self.market_data.items()
                if rid not in self.invalid_contracts
                and any(rec.get(k) is None for k in required)
            ]

    def all_data_received(self: "HasMarketData") -> bool:
        """Return ``True`` when all requested option data has been received."""
        return self.all_data_event.is_set()

    def _start_max_data_timer(self: "HasMarketData") -> None:
        """Start the global timeout timer for all market data requests.

        The timer duration is controlled by ``OPTION_MAX_MARKETDATA_TIME``.
        """
        limit = int(cfg_get("OPTION_MAX_MARKETDATA_TIME", 0))
        if limit <= 0 or self._max_data_timer is not None:
            return

        def timeout() -> None:
            missing = self.incomplete_requests()
            if missing:
                logger.warning(
                    f"⚠️ Hard timeout na {limit}s: {len(missing)} contracten ontbreken"
                )
            self.all_data_event.set()

        timer = threading.Timer(limit, timeout)
        timer.daemon = True
        self._max_data_timer = timer
        timer.start()

    def _stop_max_data_timer(self) -> None:
        """Stop and clear the global timeout timer."""
        timer = self._max_data_timer
        if timer is not None:
            timer.cancel()
            self._max_data_timer = None


__all__ = ["RequestTimerManager"]
