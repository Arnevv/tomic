from datetime import datetime

from tomic.export import (
    RunMetadata,
    build_export_path,
    export_proposals_csv,
    export_proposals_json,
    render_journal_entries,
)
from tomic.services.strategy_pipeline import StrategyProposal


def test_build_and_write_csv(tmp_path):
    run_meta = RunMetadata(
        timestamp=datetime(2024, 1, 2, 3, 4, 5),
        run_id="run123",
        symbol="AAA",
        strategy="iron_condor",
        config_hash="abc123",
    ).with_extra(
        footer_rows=[("credit", 12.5), ("breakevens", [1.0, 2.0])]
    )

    export_path = build_export_path(
        "proposal", run_meta, extension="csv", directory=tmp_path
    )

    records = [
        {
            "expiry": "2024-01-19",
            "strike": 100,
            "type": "put",
            "position": -1,
            "bid": 1.0,
            "ask": 1.2,
            "mid": 1.1,
            "delta": -0.2,
            "theta": 0.1,
            "vega": 0.05,
            "edge": 0.2,
            "manual_override": False,
            "missing_metrics": ["mid"],
            "metrics_ignored": False,
        }
    ]

    columns = [
        "expiry",
        "strike",
        "type",
        "position",
        "bid",
        "ask",
        "mid",
        "delta",
        "theta",
        "vega",
        "edge",
        "manual_override",
        "missing_metrics",
        "metrics_ignored",
    ]

    result = export_proposals_csv(records, columns=columns, path=export_path, run_meta=run_meta)
    assert result.exists()
    lines = result.read_text().splitlines()
    assert lines[0].startswith("# meta:")
    assert "run123" in lines[0]
    assert lines[-2].startswith("credit")
    assert lines[-1].startswith("breakevens")


def test_export_proposals_json(tmp_path):
    run_meta = RunMetadata(
        timestamp=datetime(2024, 1, 2, 3, 4, 5),
        run_id="run123",
        symbol="AAA",
        strategy="iron_condor",
        config_hash="abc123",
    )
    export_path = build_export_path(
        "proposal", run_meta, extension="json", directory=tmp_path
    )
    payload = {"legs": [], "metrics": {"credit": 10.0}}
    result = export_proposals_json(payload, path=export_path, run_meta=run_meta)
    content = result.read_text()
    assert "\"meta\"" in content
    assert "\"data\"" in content
    assert "run123" in content


def test_render_journal_entries_basic():
    proposal = StrategyProposal(
        strategy="iron_condor",
        legs=[
            {
                "type": "call",
                "strike": 105,
                "expiry": "2024-02-16",
                "position": -1,
                "mid": 1.25,
            }
        ],
        credit=2.5,
        margin=10.0,
        rom=0.5,
        pos=0.6,
        ev=0.7,
    )
    lines = render_journal_entries({"proposal": proposal, "symbol": "AAA", "strategy": "iron_condor"})
    assert any(line.startswith("Symbol: AAA") for line in lines)
    assert any("Long" in line or "Short" in line for line in lines[6:])
