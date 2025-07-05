from pathlib import Path
import math
from tomic.analysis.proposal_engine import load_chain_csv, suggest_strategies


def make_chain_csv(path: Path) -> None:
    rows = [
        [
            "Expiry",
            "Type",
            "Strike",
            "Bid",
            "Ask",
            "IV",
            "Delta",
            "Gamma",
            "Vega",
            "Theta",
            "Volume",
            "OpenInterest",
            "ParityDeviation",
        ],
        ["20250101", "call", "100", "1", "1.2", "0.2", "0.4", "0.1", "0.2", "-0.05", "10", "100", ""],
        ["20250101", "C", "105", "0.5", "0.7", "0.18", "0.3", "0.08", "0.15", "-0.04", "5", "50", ""],
        ["20250101", "put", "95", "0.6", "0.8", "0.22", "-0.3", "0.09", "0.18", "-0.06", "8", "80", ""],
        ["20250101", "P", "90", "0.4", "0.6", "0.25", "-0.2", "0.07", "0.16", "-0.05", "7", "70", ""],
    ]
    with open(path, "w", newline="") as f:
        for row in rows:
            f.write(",".join(row) + "\n")


def test_load_chain_csv(tmp_path: Path) -> None:
    path = tmp_path / "chain.csv"
    make_chain_csv(path)
    legs = load_chain_csv(str(path))
    assert len(legs) == 4
    assert legs[0].type == "call"
    assert legs[2].delta == -0.3


def test_suggest_vertical(tmp_path: Path) -> None:
    path = tmp_path / "chain.csv"
    make_chain_csv(path)
    chain = load_chain_csv(str(path))
    exposure = {"Delta": 40, "Theta": 0, "Vega": 0, "Gamma": 0}
    props = suggest_strategies("XYZ", chain, exposure)
    assert any(p["strategy"] == "Vertical" for p in props)


def test_suggest_condor(tmp_path: Path) -> None:
    path = tmp_path / "chain.csv"
    make_chain_csv(path)
    chain = load_chain_csv(str(path))
    exposure = {"Delta": 0, "Theta": 0, "Vega": 80, "Gamma": 0}
    props = suggest_strategies("XYZ", chain, exposure)
    assert any(p["strategy"] == "iron_condor" for p in props)


def test_condor_margin(tmp_path: Path) -> None:
    path = tmp_path / "chain.csv"
    make_chain_csv(path)
    chain = load_chain_csv(str(path))
    exposure = {"Delta": 0, "Theta": 0, "Vega": 80, "Gamma": 0}
    props = suggest_strategies("XYZ", chain, exposure)
    condor = next(p for p in props if p["strategy"] == "iron_condor")
    assert math.isclose(condor["margin"], 500.0)
    assert math.isclose(
        condor["ROM"], condor["max_profit"] / condor["margin"] * 100
    )
