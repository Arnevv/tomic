"""Utilities for coordinating throttled API usage."""

from __future__ import annotations

import asyncio
from collections import deque
import time
from typing import Awaitable, Callable, Deque

ClockFunc = Callable[[], float]
SleepFunc = Callable[[float], None]
AsyncSleepFunc = Callable[[float], Awaitable[None]]
LogFunc = Callable[[str], None]


class RateLimiter:
    """Bound the number of calls permitted during a time window.

    The limiter supports both synchronous and asynchronous flows.  By default it
    enforces ``max_calls`` across ``period`` seconds using ``time.monotonic``.
    The provided ``sleep`` and ``async_sleep`` callables are invoked whenever a
    wait is required.  Passing the module-level ``sleep`` function from a script
    keeps monkeypatch-friendly behaviour in the test-suite.
    """

    def __init__(
        self,
        max_calls: int,
        period: float,
        *,
        clock: ClockFunc | None = None,
        sleep: SleepFunc | None = None,
        async_sleep: AsyncSleepFunc | None = None,
    ) -> None:
        self.max_calls = max_calls
        self.period = max(period, 0.0)
        self._clock: ClockFunc = clock or time.monotonic
        self._sleep: SleepFunc | None = sleep or time.sleep
        self._async_sleep: AsyncSleepFunc | None = async_sleep or asyncio.sleep
        self._timestamps: Deque[float] = deque()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _enabled(self) -> bool:
        return self.max_calls > 0 and self.period >= 0.0

    def _purge(self, now: float) -> None:
        """Discard timestamps that fall outside the active window."""

        if not self._timestamps:
            return
        boundary = now - self.period
        while self._timestamps and self._timestamps[0] <= boundary:
            self._timestamps.popleft()

    def _delay_required(self, now: float) -> float:
        """Return the number of seconds required before the next call."""

        if not self._enabled():
            return 0.0
        self._purge(now)
        if len(self._timestamps) < self.max_calls:
            return 0.0
        oldest = self._timestamps[0]
        remaining = self.period - (now - oldest)
        return remaining if remaining > 0 else 0.0

    def _record(self, when: float) -> None:
        if not self._enabled():
            return
        self._timestamps.append(when)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def time_until_ready(self) -> float:
        """Return seconds until the next call is allowed (without sleeping)."""

        now = self._clock()
        return self._delay_required(now)

    def record(self) -> None:
        """Register an external call without triggering a sleep."""

        now = self._clock()
        self._purge(now)
        self._record(now)

    def wait(
        self,
        *,
        log: LogFunc | None = None,
        message: str | None = None,
    ) -> float:
        """Sleep until a slot is available and return the waited seconds."""

        if not self._enabled():
            return 0.0

        waited = 0.0
        while True:
            now = self._clock()
            delay = self._delay_required(now)
            if delay <= 0:
                self._record(now)
                return waited
            if log is not None and message is not None and waited == 0.0:
                log(message.format(wait=delay, max_calls=self.max_calls, period=self.period))
            if self._sleep is None:
                raise RuntimeError("RateLimiter sleep requested but no sleep function provided")
            self._sleep(delay)
            waited += delay

    async def wait_async(
        self,
        *,
        log: LogFunc | None = None,
        message: str | None = None,
    ) -> float:
        """Asynchronous variant of :meth:`wait`."""

        if not self._enabled():
            return 0.0

        waited = 0.0
        while True:
            now = self._clock()
            delay = self._delay_required(now)
            if delay <= 0:
                self._record(now)
                return waited
            if log is not None and message is not None and waited == 0.0:
                log(message.format(wait=delay, max_calls=self.max_calls, period=self.period))
            if self._async_sleep is None:
                raise RuntimeError(
                    "RateLimiter async wait requested but no async sleep function provided"
                )
            await self._async_sleep(delay)
            waited += delay
