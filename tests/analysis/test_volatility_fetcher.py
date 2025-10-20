"""Tests for the volatility fetcher helpers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, Tuple

import pytest

import tomic.analysis.volatility_fetcher as vf


def _tick(name: str) -> int:
    return int(getattr(vf.TickTypeEnum, name))


def _today_str(tz_name: str) -> str:
    tz = vf.ZoneInfo(tz_name)
    return datetime.now(timezone.utc).astimezone(tz).strftime("%Y%m%d")


def test_select_tick_rth_prefers_last() -> None:
    ticks = {_tick("LAST"): 20.5, _tick("MARK_PRICE"): 20.1}

    assert vf.select_tick(ticks, rth_open=True) == (_tick("LAST"), 20.5)


def test_select_tick_rth_mark_price_fallback() -> None:
    ticks = {_tick("MARK_PRICE"): 19.9}

    assert vf.select_tick(ticks, rth_open=True) == (_tick("MARK_PRICE"), 19.9)


def test_select_tick_rth_close_fallback() -> None:
    ticks = {_tick("CLOSE"): 18.2}

    assert vf.select_tick(ticks, rth_open=True) == (_tick("CLOSE"), 18.2)


def test_select_tick_offhours_prefers_last_then_mark_then_close() -> None:
    ticks = {
        _tick("LAST"): 18.6,
        _tick("MARK_PRICE"): 18.5,
        _tick("CLOSE"): 18.4,
    }

    assert vf.select_tick(ticks, rth_open=False) == (_tick("LAST"), 18.6)

    ticks = {_tick("MARK_PRICE"): 17.3, _tick("CLOSE"): 17.1}

    assert vf.select_tick(ticks, rth_open=False) == (_tick("MARK_PRICE"), 17.3)

    ticks = {_tick("CLOSE"): 16.9}

    assert vf.select_tick(ticks, rth_open=False) == (_tick("CLOSE"), 16.9)


def test_is_rth_open_true_for_open_window() -> None:
    day = _today_str("America/New_York")
    details = SimpleNamespace(
        tradingHours=f"{day}:0000-2359",
        timeZoneId="America/New_York",
    )
    now = datetime.now(timezone.utc)

    assert vf.is_rth_open(details, now) is True


def test_is_rth_open_false_for_closed_day() -> None:
    day = _today_str("America/New_York")
    details = SimpleNamespace(
        tradingHours=f"{day}:CLOSED",
        timeZoneId="America/New_York",
    )
    now = datetime.now(timezone.utc)

    assert vf.is_rth_open(details, now) is False


def test_is_rth_open_handles_midday_break() -> None:
    day = _today_str("America/New_York")
    details = SimpleNamespace(
        tradingHours=f"{day}:0930-1200,1300-1615",
        timeZoneId="America/New_York",
    )
    tz = vf.ZoneInfo("America/New_York")
    local_day = datetime.now(tz).date()
    open_local = datetime(local_day.year, local_day.month, local_day.day, 10, 0, tzinfo=tz)
    break_local = datetime(local_day.year, local_day.month, local_day.day, 12, 30, tzinfo=tz)

    assert vf.is_rth_open(details, open_local.astimezone(timezone.utc)) is True
    assert vf.is_rth_open(details, break_local.astimezone(timezone.utc)) is False


class DummyIB:
    """Minimal IB client stub for VIX tests."""

    def __init__(
        self,
        details_by_exchange: Dict[str, Any],
        snapshots: Dict[Tuple[str, int], Dict[int, float]],
    ) -> None:
        self._details = details_by_exchange
        self._snapshots = snapshots
        self.market_data_types: list[int] = []
        self.disconnected = False

    def get_contract_details(self, contract: Any, timeout_ms: int | None = None) -> Any:
        return self._details.get(contract.exchange)

    def request_snapshot_with_mdtype(
        self, contract: Any, md_type: int, timeout_ms: int
    ) -> Dict[int, float]:
        payload = self._snapshots.get((contract.exchange, md_type))
        if isinstance(payload, Exception):
            raise payload
        return dict(payload or {})

    def disconnect(self) -> None:
        self.disconnected = True


class FakeContract:
    """Minimal contract stub to mimic ibapi Contract."""

    def __init__(self) -> None:
        self.symbol = ""
        self.secType = ""
        self.currency = ""
        self.exchange = ""
        self.primaryExchange = ""


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    vf._VIX_CACHE.clear()
    vf._CONTRACT_DETAILS_CACHE.clear()


def _prepare_ib_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    details: Dict[str, Any],
    snapshots: Dict[Tuple[str, int], Dict[int, float]],
    exchanges: list[str] | None = None,
) -> None:
    config = vf.VixConfig(provider_order=["ibkr"])
    monkeypatch.setattr(vf, "_vix_settings", lambda: config)
    overrides = {
        "IB_HOST": "127.0.0.1",
        "IB_PAPER_MODE": True,
        "IB_PORT": 7497,
        "IB_MARKETDATA_CLIENT_ID": 901,
        "VIX_EXCHANGES": exchanges or ["CBOE"],
        "VIX_PRICE_POLICY": "last_known",
        "VIX_RTH_TIMEOUT_MS": 1500,
        "VIX_OFFHOURS_TIMEOUT_MS": 1500,
        "VIX_LOG_TICK_SOURCE": True,
        "CONTRACT_DETAILS_TIMEOUT": 2,
        "VIX_MEMORY_TTL_SECONDS": 0,
    }

    def fake_cfg_get(key: str, default: Any = None) -> Any:
        return overrides.get(key, default)

    monkeypatch.setattr(vf, "cfg_get", fake_cfg_get)
    monkeypatch.setattr(vf, "connect_ib", lambda **_: DummyIB(details, snapshots))
    monkeypatch.setattr(vf, "Contract", FakeContract)


def test_ibkr_rth_uses_mark_price(monkeypatch: pytest.MonkeyPatch) -> None:
    day = _today_str("America/New_York")
    details = {
        "CBOE": SimpleNamespace(
            tradingHours=f"{day}:0000-2359",
            timeZoneId="America/New_York",
        )
    }
    snapshots = {("CBOE", 1): {_tick("MARK_PRICE"): 25.31}}
    _prepare_ib_env(monkeypatch, details=details, snapshots=snapshots)

    value, source, error = asyncio.run(vf._fetch_vix_from_ibkr())

    assert error is None
    assert value is not None and abs(value - 25.31) < 1e-9
    assert source == "ibkr:CBOE|MARK_PRICE|md=1"


def test_ibkr_rth_falls_back_to_delayed_last(monkeypatch: pytest.MonkeyPatch) -> None:
    day = _today_str("America/New_York")
    details = {
        "CBOE": SimpleNamespace(
            tradingHours=f"{day}:0000-2359",
            timeZoneId="America/New_York",
        )
    }
    snapshots = {
        ("CBOE", 1): {},
        ("CBOE", 2): {},
        ("CBOE", 3): {_tick("DELAYED_LAST"): 22.4},
    }
    _prepare_ib_env(monkeypatch, details=details, snapshots=snapshots)

    value, source, error = asyncio.run(vf._fetch_vix_from_ibkr())

    assert error is None
    assert value is not None and abs(value - 22.4) < 1e-9
    assert source == "ibkr:CBOE|DELAYED_LAST|md=3"


def test_ibkr_offhours_prefers_close(monkeypatch: pytest.MonkeyPatch) -> None:
    day = _today_str("America/New_York")
    details = {
        "CBOE": SimpleNamespace(
            tradingHours=f"{day}:CLOSED",
            timeZoneId="America/New_York",
        )
    }
    snapshots = {
        ("CBOE", 1): {},
        ("CBOE", 2): {_tick("CLOSE"): 20.78},
    }
    _prepare_ib_env(monkeypatch, details=details, snapshots=snapshots)

    value, source, error = asyncio.run(vf._fetch_vix_from_ibkr())

    assert error is None
    assert value is not None and abs(value - 20.78) < 1e-9
    assert source == "ibkr:CBOE|CLOSE|md=2"


def test_ibkr_offhours_falls_back_to_delayed_close(monkeypatch: pytest.MonkeyPatch) -> None:
    day = _today_str("America/New_York")
    details = {
        "CBOE": SimpleNamespace(
            tradingHours=f"{day}:CLOSED",
            timeZoneId="America/New_York",
        )
    }
    snapshots = {
        ("CBOE", 1): {},
        ("CBOE", 2): {},
        ("CBOE", 4): {_tick("DELAYED_CLOSE"): 19.88},
    }
    _prepare_ib_env(monkeypatch, details=details, snapshots=snapshots)

    value, source, error = asyncio.run(vf._fetch_vix_from_ibkr())

    assert error is None
    assert value is not None and abs(value - 19.88) < 1e-9
    assert source == "ibkr:CBOE|DELAYED_CLOSE|md=4"


def test_ibkr_offhours_prefers_last_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    day = _today_str("America/New_York")
    details = {
        "CBOE": SimpleNamespace(
            tradingHours=f"{day}:CLOSED",
            timeZoneId="America/New_York",
        )
    }
    snapshots = {
        ("CBOE", 1): {_tick("LAST"): 18.59},
        ("CBOE", 2): {_tick("CLOSE"): 20.78},
    }
    _prepare_ib_env(monkeypatch, details=details, snapshots=snapshots)

    value, source, error = asyncio.run(vf._fetch_vix_from_ibkr())

    assert error is None
    assert value is not None and abs(value - 18.59) < 1e-9
    assert source == "ibkr:CBOE|LAST|md=1"


def test_iter_exchanges_prioritizes_plain_cboe(monkeypatch: pytest.MonkeyPatch) -> None:
    config = vf.VixConfig(provider_order=["ibkr"], ib_exchanges=["CBOE", "CBOEIND"])
    monkeypatch.setattr(vf, "_vix_settings", lambda: config)

    def fake_cfg(key: str, default: Any = None) -> Any:
        if key == "VIX_EXCHANGES":
            return ["CBOEIND", "CBOE"]
        return default

    monkeypatch.setattr(vf, "cfg_get", fake_cfg)

    result = vf._iter_exchanges(config)

    assert result[0].split("@", 1)[0].upper() == "CBOE"


def test_ibkr_skips_invalid_exchange_error(monkeypatch: pytest.MonkeyPatch) -> None:
    day = _today_str("America/New_York")
    details = {
        "CBOEIND": SimpleNamespace(
            tradingHours=f"{day}:CLOSED",
            timeZoneId="America/New_York",
        ),
        "CBOE": SimpleNamespace(
            tradingHours=f"{day}:0000-2359",
            timeZoneId="America/New_York",
        ),
    }
    snapshots: Dict[Tuple[str, int], Dict[int, float]] = {
        ("CBOEIND", 2): RuntimeError("IB error 200: destination or exchange selected is Invalid"),
        ("CBOE", 1): {_tick("LAST"): 24.5},
    }
    _prepare_ib_env(
        monkeypatch,
        details=details,
        snapshots=snapshots,
        exchanges=["CBOEIND", "CBOE"],
    )
    monkeypatch.setattr(vf, "_iter_exchanges", lambda settings: ["CBOEIND", "CBOE"])

    value, source, error = asyncio.run(vf._fetch_vix_from_ibkr())

    assert error is None
    assert value is not None and abs(value - 24.5) < 1e-9
    assert source == "ibkr:CBOE|LAST|md=1"


def test_fetch_volatility_metrics_async_skips_file_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    day = _today_str("America/New_York")
    details = {
        "CBOE": SimpleNamespace(
            tradingHours=f"{day}:0000-2359",
            timeZoneId="America/New_York",
        )
    }
    snapshots = {("CBOE", 1): {_tick("LAST"): 21.0}}
    _prepare_ib_env(monkeypatch, details=details, snapshots=snapshots)
    config = vf.VixConfig(provider_order=["ibkr"], daily_store=str(tmp_path / "vix.csv"))
    monkeypatch.setattr(vf, "_vix_settings", lambda: config)

    metrics = asyncio.run(vf.fetch_volatility_metrics_async("SPY"))

    assert abs(metrics["vix"] - 21.0) < 1e-9
    assert metrics["vix_source"] == "ibkr:CBOE|LAST|md=1"
    assert not (tmp_path / "vix.csv").exists()
