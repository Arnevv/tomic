"""Tests for IBClient request handling in tomic/api/ib_connection.py"""
import sys
import types
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

# Create minimal stubs so ib_connection can be imported without the real IB API
client_stub = types.ModuleType("ibapi.client")
client_stub.EClient = type(
    "EClient",
    (),
    {
        "__init__": lambda self, wrapper=None: None,
        "connect": lambda self, host, port, clientId: None,
        "run": lambda self: None,
        "disconnect": lambda self: None,
        "reqContractDetails": lambda self, reqId, contract: None,
        "cancelContractDetails": lambda self, reqId: None,
        "reqMarketDataType": lambda self, mdType: None,
        "reqMktData": lambda self, reqId, contract, genericTickList, snapshot, regulatorySnapshot, mktDataOptions: None,
        "cancelMktData": lambda self, reqId: None,
    },
)
wrapper_stub = types.ModuleType("ibapi.wrapper")
wrapper_stub.EWrapper = type("EWrapper", (), {})
sys.modules.setdefault("ibapi.client", client_stub)
sys.modules.setdefault("ibapi.wrapper", wrapper_stub)

from tomic.api.ib_connection import IBClient, RequestState


class MockContract:
    """Mock IB contract for testing."""
    def __init__(self, symbol="SPY", secType="STK"):
        self.symbol = symbol
        self.secType = secType


class MockContractDetails:
    """Mock contract details returned by IB."""
    def __init__(self, symbol="SPY"):
        self.contract = MockContract(symbol)


# =============================================================================
# Contract Details Tests
# =============================================================================

class TestGetContractDetails:
    """Tests for get_contract_details method."""

    def test_success_single_detail(self):
        """Test successful retrieval of contract details."""
        client = IBClient()
        contract = MockContract("SPY")

        def simulate_callback():
            time.sleep(0.01)
            req_id = 1
            detail = MockContractDetails("SPY")
            client.contractDetails(req_id, detail)
            client.contractDetailsEnd(req_id)

        thread = threading.Thread(target=simulate_callback)
        thread.start()

        result = client.get_contract_details(contract, timeout_ms=1000)
        thread.join()

        assert result is not None
        assert result.contract.symbol == "SPY"

    def test_success_multiple_details(self):
        """Test retrieval of multiple contract details (returns first)."""
        client = IBClient()
        contract = MockContract("SPY")

        def simulate_callback():
            time.sleep(0.01)
            req_id = 1
            for i in range(3):
                detail = MockContractDetails(f"SPY{i}")
                client.contractDetails(req_id, detail)
            client.contractDetailsEnd(req_id)

        thread = threading.Thread(target=simulate_callback)
        thread.start()

        result = client.get_contract_details(contract, timeout_ms=1000)
        thread.join()

        # Should return first detail for backward compatibility
        assert result is not None
        assert result.contract.symbol == "SPY0"

    def test_timeout(self):
        """Test that timeout is raised when no callback received."""
        client = IBClient()
        contract = MockContract("SPY")

        with pytest.raises(TimeoutError) as exc_info:
            client.get_contract_details(contract, timeout_ms=50)

        assert "timeout" in str(exc_info.value).lower()
        assert "SPY" in str(exc_info.value)

    def test_error_callback(self):
        """Test that error callback triggers exception."""
        client = IBClient()
        contract = MockContract("SPY")

        def simulate_error():
            time.sleep(0.01)
            req_id = 1
            client.error(req_id, 321, "No security definition found")

        thread = threading.Thread(target=simulate_error)
        thread.start()

        with pytest.raises(RuntimeError) as exc_info:
            client.get_contract_details(contract, timeout_ms=1000)

        thread.join()
        assert "No security definition found" in str(exc_info.value)

    def test_empty_details_returns_none(self):
        """Test that empty result returns None."""
        client = IBClient()
        contract = MockContract("SPY")

        def simulate_callback():
            time.sleep(0.01)
            req_id = 1
            # No details, just end
            client.contractDetailsEnd(req_id)

        thread = threading.Thread(target=simulate_callback)
        thread.start()

        result = client.get_contract_details(contract, timeout_ms=1000)
        thread.join()

        assert result is None

    def test_unknown_req_id_callback(self):
        """Test that callback with unknown reqId doesn't crash."""
        client = IBClient()

        # Should not raise
        client.contractDetails(999, MockContractDetails())
        client.contractDetailsEnd(999)

    def test_request_state_cleanup(self):
        """Test that request state is cleaned up after completion."""
        client = IBClient()
        contract = MockContract("SPY")

        def simulate_callback():
            time.sleep(0.01)
            req_id = 1
            client.contractDetails(req_id, MockContractDetails())
            client.contractDetailsEnd(req_id)

        thread = threading.Thread(target=simulate_callback)
        thread.start()

        client.get_contract_details(contract, timeout_ms=1000)
        thread.join()

        # State should be cleaned up
        assert len(client._requests) == 0

    def test_request_state_cleanup_on_timeout(self):
        """Test that request state is cleaned up even on timeout."""
        client = IBClient()
        contract = MockContract("SPY")

        with pytest.raises(TimeoutError):
            client.get_contract_details(contract, timeout_ms=50)

        # State should be cleaned up
        assert len(client._requests) == 0


# =============================================================================
# Snapshot Tests
# =============================================================================

class TestRequestSnapshotWithMdtype:
    """Tests for request_snapshot_with_mdtype method."""

    def test_success_basic(self):
        """Test successful snapshot retrieval."""
        client = IBClient()
        contract = MockContract("SPY")

        def simulate_callback():
            time.sleep(0.01)
            req_id = 1
            # BID=1, ASK=2, LAST=4
            client.tickPrice(req_id, 1, 100.0, None)
            client.tickPrice(req_id, 2, 101.0, None)
            client.tickPrice(req_id, 4, 100.5, None)
            client.tickSnapshotEnd(req_id)

        thread = threading.Thread(target=simulate_callback)
        thread.start()

        result = client.request_snapshot_with_mdtype(contract, 1, timeout_ms=1000)
        thread.join()

        assert result[1] == 100.0  # bid
        assert result[2] == 101.0  # ask
        assert result[4] == 100.5  # last

    def test_sentinel_prices_filtered(self):
        """Test that negative/sentinel prices are filtered out."""
        client = IBClient()
        contract = MockContract("SPY")

        def simulate_callback():
            time.sleep(0.01)
            req_id = 1
            client.tickPrice(req_id, 1, -1.0, None)   # sentinel, should be filtered
            client.tickPrice(req_id, 2, 101.0, None)  # valid
            client.tickPrice(req_id, 4, 0.0, None)    # sentinel, should be filtered
            client.tickSnapshotEnd(req_id)

        thread = threading.Thread(target=simulate_callback)
        thread.start()

        result = client.request_snapshot_with_mdtype(contract, 1, timeout_ms=1000)
        thread.join()

        assert 1 not in result  # bid filtered
        assert result[2] == 101.0  # ask valid
        assert 4 not in result  # last filtered

    def test_timeout(self):
        """Test that timeout is raised when no callback received."""
        client = IBClient()
        contract = MockContract("SPY")

        with pytest.raises(TimeoutError) as exc_info:
            client.request_snapshot_with_mdtype(contract, 1, timeout_ms=50)

        assert "timeout" in str(exc_info.value).lower()

    def test_error_callback(self):
        """Test that error callback triggers exception."""
        client = IBClient()
        contract = MockContract("SPY")

        def simulate_error():
            time.sleep(0.01)
            req_id = 1
            client.error(req_id, 162, "Historical data service error")

        thread = threading.Thread(target=simulate_error)
        thread.start()

        with pytest.raises(RuntimeError) as exc_info:
            client.request_snapshot_with_mdtype(contract, 1, timeout_ms=1000)

        thread.join()
        assert "Historical data service error" in str(exc_info.value)

    def test_unknown_req_id_callback(self):
        """Test that callback with unknown reqId doesn't crash."""
        client = IBClient()

        # Should not raise
        client.tickPrice(999, 1, 100.0, None)
        client.tickSnapshotEnd(999)

    def test_empty_snapshot(self):
        """Test snapshot with no tick data."""
        client = IBClient()
        contract = MockContract("SPY")

        def simulate_callback():
            time.sleep(0.01)
            req_id = 1
            client.tickSnapshotEnd(req_id)

        thread = threading.Thread(target=simulate_callback)
        thread.start()

        result = client.request_snapshot_with_mdtype(contract, 1, timeout_ms=1000)
        thread.join()

        assert result == {}

    def test_request_state_cleanup(self):
        """Test that request state is cleaned up after completion."""
        client = IBClient()
        contract = MockContract("SPY")

        def simulate_callback():
            time.sleep(0.01)
            req_id = 1
            client.tickPrice(req_id, 1, 100.0, None)
            client.tickSnapshotEnd(req_id)

        thread = threading.Thread(target=simulate_callback)
        thread.start()

        client.request_snapshot_with_mdtype(contract, 1, timeout_ms=1000)
        thread.join()

        assert len(client._requests) == 0


# =============================================================================
# Concurrency Tests
# =============================================================================

class TestConcurrency:
    """Tests for concurrent request handling."""

    def test_multiple_contract_details_requests(self):
        """Test multiple concurrent contract details requests."""
        client = IBClient()
        results = {}
        errors = []

        def make_request(symbol, req_id_offset):
            try:
                contract = MockContract(symbol)

                def simulate_callback():
                    time.sleep(0.02)
                    req_id = req_id_offset
                    detail = MockContractDetails(symbol)
                    client.contractDetails(req_id, detail)
                    client.contractDetailsEnd(req_id)

                cb_thread = threading.Thread(target=simulate_callback)
                cb_thread.start()

                result = client.get_contract_details(contract, timeout_ms=1000)
                results[symbol] = result
                cb_thread.join()
            except Exception as e:
                errors.append((symbol, e))

        # Start 5 concurrent requests
        threads = []
        for i, symbol in enumerate(["SPY", "QQQ", "IWM", "DIA", "VTI"], start=1):
            t = threading.Thread(target=make_request, args=(symbol, i))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == 5
        for symbol in ["SPY", "QQQ", "IWM", "DIA", "VTI"]:
            assert symbol in results
            assert results[symbol].contract.symbol == symbol

    def test_mixed_requests(self):
        """Test concurrent mix of contract details and snapshot requests."""
        client = IBClient()
        results = {}
        errors = []

        def make_contract_request(symbol, req_id):
            try:
                contract = MockContract(symbol)

                def simulate_callback():
                    time.sleep(0.02)
                    detail = MockContractDetails(symbol)
                    client.contractDetails(req_id, detail)
                    client.contractDetailsEnd(req_id)

                cb_thread = threading.Thread(target=simulate_callback)
                cb_thread.start()

                result = client.get_contract_details(contract, timeout_ms=1000)
                results[f"contract_{symbol}"] = result
                cb_thread.join()
            except Exception as e:
                errors.append((f"contract_{symbol}", e))

        def make_snapshot_request(symbol, req_id):
            try:
                contract = MockContract(symbol)

                def simulate_callback():
                    time.sleep(0.02)
                    client.tickPrice(req_id, 1, 100.0, None)
                    client.tickPrice(req_id, 2, 101.0, None)
                    client.tickSnapshotEnd(req_id)

                cb_thread = threading.Thread(target=simulate_callback)
                cb_thread.start()

                result = client.request_snapshot_with_mdtype(contract, 1, timeout_ms=1000)
                results[f"snapshot_{symbol}"] = result
                cb_thread.join()
            except Exception as e:
                errors.append((f"snapshot_{symbol}", e))

        # Start mixed concurrent requests
        threads = []
        t1 = threading.Thread(target=make_contract_request, args=("SPY", 1))
        t2 = threading.Thread(target=make_snapshot_request, args=("QQQ", 2))
        t3 = threading.Thread(target=make_contract_request, args=("IWM", 3))
        t4 = threading.Thread(target=make_snapshot_request, args=("DIA", 4))

        for t in [t1, t2, t3, t4]:
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert "contract_SPY" in results
        assert "snapshot_QQQ" in results
        assert "contract_IWM" in results
        assert "snapshot_DIA" in results

        # Verify results are correct type
        assert results["contract_SPY"].contract.symbol == "SPY"
        assert results["snapshot_QQQ"][1] == 100.0

    def test_no_cross_contamination(self):
        """Test that callbacks for different reqIds don't contaminate each other."""
        client = IBClient()

        # Setup two requests
        state1 = RequestState(result=[], kind="contract_details")
        state2 = RequestState(result=[], kind="contract_details")

        with client._requests_lock:
            client._requests[1] = state1
            client._requests[2] = state2

        # Send callbacks in interleaved order
        client.contractDetails(1, MockContractDetails("SPY"))
        client.contractDetails(2, MockContractDetails("QQQ"))
        client.contractDetails(1, MockContractDetails("SPY2"))
        client.contractDetailsEnd(2)
        client.contractDetailsEnd(1)

        # Verify no cross-contamination
        assert len(state1.result) == 2
        assert state1.result[0].contract.symbol == "SPY"
        assert state1.result[1].contract.symbol == "SPY2"

        assert len(state2.result) == 1
        assert state2.result[0].contract.symbol == "QQQ"


# =============================================================================
# Error Callback Tests
# =============================================================================

class TestErrorCallback:
    """Tests for error callback handling."""

    def test_error_sets_state(self):
        """Test that error callback properly sets state."""
        client = IBClient()

        state = RequestState(result=[], kind="contract_details")
        with client._requests_lock:
            client._requests[1] = state

        client.error(1, 321, "Test error message")

        assert state.error == "Test error message"
        assert state.error_code == 321
        assert state.event.is_set()

    def test_global_error_reqid_minus_one(self):
        """Test that global errors (reqId=-1) are logged but don't crash."""
        client = IBClient()

        # Should not raise
        client.error(-1, 504, "Not connected")

    def test_unknown_reqid_error(self):
        """Test that error for unknown reqId doesn't crash."""
        client = IBClient()

        # Should not raise
        client.error(999, 321, "Unknown request")


# =============================================================================
# Logging Tests
# =============================================================================

class TestLogging:
    """Tests for logging output."""

    def test_contract_details_logs_start(self, caplog):
        """Test that start logging includes key info."""
        import logging
        caplog.set_level(logging.INFO)

        client = IBClient()
        contract = MockContract("SPY")

        def simulate_callback():
            time.sleep(0.01)
            client.contractDetails(1, MockContractDetails())
            client.contractDetailsEnd(1)

        thread = threading.Thread(target=simulate_callback)
        thread.start()

        client.get_contract_details(contract, timeout_ms=1000)
        thread.join()

        # Check log messages
        log_text = caplog.text
        assert "[IB] start" in log_text
        assert "reqId=1" in log_text
        assert "contract_details" in log_text
        assert "SPY" in log_text

    def test_contract_details_logs_done(self, caplog):
        """Test that done logging includes duration and count."""
        import logging
        caplog.set_level(logging.INFO)

        client = IBClient()
        contract = MockContract("SPY")

        def simulate_callback():
            time.sleep(0.01)
            client.contractDetails(1, MockContractDetails())
            client.contractDetailsEnd(1)

        thread = threading.Thread(target=simulate_callback)
        thread.start()

        client.get_contract_details(contract, timeout_ms=1000)
        thread.join()

        log_text = caplog.text
        assert "[IB] done" in log_text
        assert "details=1" in log_text
        assert "dur=" in log_text

    def test_snapshot_logs_fields(self, caplog):
        """Test that snapshot done logging includes field names."""
        import logging
        caplog.set_level(logging.INFO)

        client = IBClient()
        contract = MockContract("SPY")

        def simulate_callback():
            time.sleep(0.01)
            client.tickPrice(1, 1, 100.0, None)  # bid
            client.tickPrice(1, 2, 101.0, None)  # ask
            client.tickSnapshotEnd(1)

        thread = threading.Thread(target=simulate_callback)
        thread.start()

        client.request_snapshot_with_mdtype(contract, 1, timeout_ms=1000)
        thread.join()

        log_text = caplog.text
        assert "[IB] done" in log_text
        assert "snapshot" in log_text
        assert "fields=" in log_text
        # Should contain bid and ask
        assert "bid" in log_text
        assert "ask" in log_text

    def test_timeout_logs_warning(self, caplog):
        """Test that timeout logs a warning."""
        import logging
        caplog.set_level(logging.WARNING)

        client = IBClient()
        contract = MockContract("SPY")

        with pytest.raises(TimeoutError):
            client.get_contract_details(contract, timeout_ms=50)

        log_text = caplog.text
        assert "[IB] timeout" in log_text
        assert "SPY" in log_text

    def test_error_logs_error(self, caplog):
        """Test that error callback logs an error."""
        import logging
        caplog.set_level(logging.ERROR)

        client = IBClient()
        contract = MockContract("SPY")

        def simulate_error():
            time.sleep(0.01)
            client.error(1, 321, "Test error")

        thread = threading.Thread(target=simulate_error)
        thread.start()

        with pytest.raises(RuntimeError):
            client.get_contract_details(contract, timeout_ms=1000)

        thread.join()

        log_text = caplog.text
        assert "[IB] error" in log_text
        assert "321" in log_text
        assert "Test error" in log_text
