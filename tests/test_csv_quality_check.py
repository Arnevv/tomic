import csv
from tomic.cli.csv_quality_check import analyze_csv


def test_minus_one_quotes(tmp_path):
    path = tmp_path / "chain.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "bid",
                "ask",
                "strike",
                "iv",
                "delta",
                "gamma",
                "vega",
                "theta",
                "expiry",
            ]
        )
        writer.writerow(
            ["1", "1.2", "100", "0.2", "0.5", "0.1", "0.2", "-0.1", "20250101"]
        )
        writer.writerow(
            ["0.5", "-1", "100", "0.2", "0.5", "0.1", "0.2", "-0.1", "20250101"]
        )
        writer.writerow(
            ["-1", "0.8", "100", "0.2", "0.5", "0.1", "0.2", "-0.1", "20250101"]
        )
    stats = analyze_csv(path)
    assert stats["minus_one_quotes"] == 2
