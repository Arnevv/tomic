from tomic.cli.strategy_dashboard import extract_exit_rules
from tomic.journal.utils import save_json


def test_extract_exit_rules_reads_structured_object(tmp_path):
    journal_path = tmp_path / "journal.json"
    save_json(
        [
            {
                "Symbool": "ABC",
                "Expiry": "2024-01-19",
                "Premium": 1.0,
                "ExitRules": {
                    "spot_below": 90.0,
                    "spot_above": 110.0,
                    "target_profit_pct": 50.0,
                    "days_before_expiry": 7,
                },
            }
        ],
        journal_path,
    )

    rules = extract_exit_rules(str(journal_path))
    key = ("ABC", "2024-01-19")
    assert key in rules
    assert rules[key]["spot_below"] == 90.0
    assert rules[key]["target_profit_pct"] == 50.0
