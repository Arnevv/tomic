from tomic.analysis.rules import evaluate_rules


def test_evaluate_rules_basic():
    rules = [{"condition": "x > 5", "message": "high"}]
    assert evaluate_rules(rules, {"x": 10}) == ["high"]
