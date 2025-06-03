import json

from tomic.journal import service as svc


def test_add_trade_logs(tmp_path, monkeypatch):
    path = tmp_path / "journal.json"
    path.write_text("[]")
    messages: list[str] = []
    monkeypatch.setattr(
        svc.logger, "info", lambda msg, *a, **k: messages.append(msg % a if a else msg)
    )

    svc.add_trade({"TradeID": "1"}, path)
    data = json.loads(path.read_text())
    assert any(trade.get("TradeID") == "1" for trade in data)
    assert any("Trade added" in m for m in messages)


def test_update_trade_logs(tmp_path, monkeypatch):
    path = tmp_path / "journal.json"
    path.write_text(json.dumps([{"TradeID": "1", "Status": "Open"}]))
    infos: list[str] = []
    monkeypatch.setattr(
        svc.logger, "info", lambda msg, *a, **k: infos.append(msg % a if a else msg)
    )

    updated = svc.update_trade("1", {"Status": "Closed"}, path)
    data = json.loads(path.read_text())
    assert updated
    assert data[0]["Status"] == "Closed"
    assert any("Trade updated" in m for m in infos)


def test_update_trade_warns(tmp_path, monkeypatch):
    path = tmp_path / "journal.json"
    path.write_text("[]")
    warnings: list[str] = []
    monkeypatch.setattr(
        svc.logger,
        "warning",
        lambda msg, *a, **k: warnings.append(msg % a if a else msg),
    )

    res = svc.update_trade("X", {"foo": 1}, path)
    assert not res
    assert any("Trade not found" in w for w in warnings)
