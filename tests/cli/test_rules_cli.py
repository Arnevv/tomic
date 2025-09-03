from tomic.cli import rules

VALID = """
version: 1
strike:
  delta_min: -0.8
  delta_max: 0.8
  min_rom: 0
  min_edge: 0
  min_pos: 0
  min_ev: 0
  skew_min: -0.1
  skew_max: 0.1
  term_min: -0.2
  term_max: 0.2
strategy:
  score_weight_rom: 0.5
  score_weight_pos: 0.3
  score_weight_ev: 0.2
  acceptance:
    require_positive_credit_for: []
market_data:
  min_option_volume: 0
  min_option_open_interest: 0
alerts:
  nearest_strike_tolerance_percent: 1
  skew_threshold: 0.05
  iv_hv_min_spread: 0.03
  iv_rank_threshold: 0.30
  entry_checks: []
portfolio:
  vega_to_condor: 50
  vega_to_calendar: -50
  condor_gates: {}
  calendar_gates: {}
"""


def test_show(capsys):
    assert rules.main(["show"]) == 0
    out = capsys.readouterr().out
    assert "delta_min" in out


def test_validate_ok(tmp_path, capsys):
    p = tmp_path / "crit.yaml"
    p.write_text(VALID)
    code = rules.main(["validate", str(p)])
    assert code == 0
    assert "Configuration OK" in capsys.readouterr().out


def test_validate_bad(tmp_path, capsys):
    p = tmp_path / "bad.yaml"
    p.write_text("strike: {}")
    code = rules.main(["validate", str(p)])
    assert code == 1
    assert "Invalid configuration" in capsys.readouterr().out
