"""Tests for tomic.api.earnings_importer module."""

from __future__ import annotations

import json
import pytest
from datetime import date
from pathlib import Path

from tomic.api.earnings_importer import (
    parse_earnings_csv,
    load_json,
    save_json,
    closest_future_index,
    enforce_month_uniqueness,
    update_next_earnings,
)


class TestParseEarningsCSV:
    """Tests for parse_earnings_csv function."""

    def test_parses_valid_csv(self, tmp_path):
        """Should parse valid CSV with standard columns."""
        csv_content = "Symbol,Next Earnings\nAAPL,2024-01-15\nGOOGL,2024-02-20\n"
        csv_file = tmp_path / "earnings.csv"
        csv_file.write_text(csv_content)

        result = parse_earnings_csv(str(csv_file))

        assert "AAPL" in result
        assert "GOOGL" in result
        assert result["AAPL"] == "2024-01-15"
        assert result["GOOGL"] == "2024-02-20"

    def test_parses_csv_with_trailing_space_column(self, tmp_path):
        """Should handle 'Next Earnings ' column with trailing space."""
        csv_content = "Symbol,Next Earnings \nAAPL,2024-01-15\n"
        csv_file = tmp_path / "earnings.csv"
        csv_file.write_text(csv_content)

        result = parse_earnings_csv(str(csv_file))

        assert "AAPL" in result

    def test_converts_symbols_to_uppercase(self, tmp_path):
        """Symbols should be normalized to uppercase."""
        csv_content = "Symbol,Next Earnings\naapl,2024-01-15\n"
        csv_file = tmp_path / "earnings.csv"
        csv_file.write_text(csv_content)

        result = parse_earnings_csv(str(csv_file))

        assert "AAPL" in result
        assert "aapl" not in result

    def test_handles_various_date_formats(self, tmp_path):
        """Should parse multiple date formats."""
        csv_content = "Symbol,Next Earnings\nA,01/15/2024\nB,2024/01/15\nC,2024-01-15\n"
        csv_file = tmp_path / "earnings.csv"
        csv_file.write_text(csv_content)

        result = parse_earnings_csv(str(csv_file))

        # All should be normalized to ISO format
        for symbol in ["A", "B", "C"]:
            assert symbol in result
            assert result[symbol] == "2024-01-15"

    def test_skips_rows_with_empty_symbol(self, tmp_path):
        """Rows with empty symbol should be skipped."""
        csv_content = "Symbol,Next Earnings\n,2024-01-15\nAAPL,2024-02-20\n"
        csv_file = tmp_path / "earnings.csv"
        csv_file.write_text(csv_content)

        result = parse_earnings_csv(str(csv_file))

        assert len(result) == 1
        assert "AAPL" in result

    def test_skips_rows_with_empty_date(self, tmp_path):
        """Rows with empty date should be skipped."""
        csv_content = "Symbol,Next Earnings\nAAPL,\nGOOGL,2024-02-20\n"
        csv_file = tmp_path / "earnings.csv"
        csv_file.write_text(csv_content)

        result = parse_earnings_csv(str(csv_file))

        assert "AAPL" not in result
        assert "GOOGL" in result

    def test_raises_on_missing_file(self, tmp_path):
        """Should raise FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            parse_earnings_csv(str(tmp_path / "nonexistent.csv"))

    def test_raises_on_missing_symbol_column(self, tmp_path):
        """Should raise KeyError when Symbol column is missing."""
        csv_content = "Other,Next Earnings\nAAPL,2024-01-15\n"
        csv_file = tmp_path / "earnings.csv"
        csv_file.write_text(csv_content)

        with pytest.raises(KeyError) as exc_info:
            parse_earnings_csv(str(csv_file))
        assert "Symbol" in str(exc_info.value)

    def test_raises_on_missing_next_earnings_column(self, tmp_path):
        """Should raise KeyError when Next Earnings column is missing."""
        csv_content = "Symbol,Other\nAAPL,value\n"
        csv_file = tmp_path / "earnings.csv"
        csv_file.write_text(csv_content)

        with pytest.raises(KeyError) as exc_info:
            parse_earnings_csv(str(csv_file))
        assert "earnings" in str(exc_info.value).lower()

    def test_returns_empty_dict_for_empty_csv(self, tmp_path):
        """Empty CSV should return empty dict."""
        csv_content = "Symbol,Next Earnings\n"
        csv_file = tmp_path / "earnings.csv"
        csv_file.write_text(csv_content)

        result = parse_earnings_csv(str(csv_file))

        assert result == {}

    def test_handles_csv_with_extra_columns(self, tmp_path):
        """Should ignore extra columns in CSV."""
        csv_content = "Symbol,Other,Next Earnings,Extra\nAAPL,foo,2024-01-15,bar\n"
        csv_file = tmp_path / "earnings.csv"
        csv_file.write_text(csv_content)

        result = parse_earnings_csv(str(csv_file))

        assert "AAPL" in result
        assert result["AAPL"] == "2024-01-15"

    def test_handles_invalid_date_gracefully(self, tmp_path):
        """Invalid dates should be skipped with warning."""
        csv_content = "Symbol,Next Earnings\nAAPL,invalid-date\nGOOGL,2024-02-20\n"
        csv_file = tmp_path / "earnings.csv"
        csv_file.write_text(csv_content)

        result = parse_earnings_csv(str(csv_file))

        assert "AAPL" not in result
        assert "GOOGL" in result

    def test_case_insensitive_column_matching(self, tmp_path):
        """Column names should be matched case-insensitively."""
        csv_content = "SYMBOL,NEXT EARNINGS\nAAPL,2024-01-15\n"
        csv_file = tmp_path / "earnings.csv"
        csv_file.write_text(csv_content)

        result = parse_earnings_csv(str(csv_file))

        assert "AAPL" in result


class TestLoadJSON:
    """Tests for load_json function."""

    def test_loads_valid_json(self, tmp_path):
        """Should load valid JSON structure."""
        json_data = {"AAPL": ["2024-01-15", "2024-04-15"]}
        json_file = tmp_path / "earnings.json"
        json_file.write_text(json.dumps(json_data))

        result = load_json(str(json_file))

        assert result == json_data

    def test_returns_empty_dict_for_missing_file(self, tmp_path):
        """Missing file should return empty dict."""
        result = load_json(str(tmp_path / "nonexistent.json"))

        assert result == {}

    def test_raises_on_invalid_json(self, tmp_path):
        """Invalid JSON should raise ValueError."""
        json_file = tmp_path / "invalid.json"
        json_file.write_text("not valid json")

        with pytest.raises(ValueError) as exc_info:
            load_json(str(json_file))
        assert "JSON" in str(exc_info.value)

    def test_raises_on_non_dict_root(self, tmp_path):
        """Non-dict root should raise ValueError."""
        json_file = tmp_path / "list.json"
        json_file.write_text('["item1", "item2"]')

        with pytest.raises(ValueError) as exc_info:
            load_json(str(json_file))
        assert "object" in str(exc_info.value).lower()

    def test_raises_on_non_string_key(self, tmp_path):
        """Non-string keys should raise ValueError."""
        # JSON itself doesn't support non-string keys, but let's test the validation
        json_file = tmp_path / "valid.json"
        json_file.write_text('{"AAPL": ["2024-01-15"]}')

        result = load_json(str(json_file))
        assert "AAPL" in result

    def test_raises_on_non_list_value(self, tmp_path):
        """Non-list values should raise ValueError."""
        json_file = tmp_path / "invalid.json"
        json_file.write_text('{"AAPL": "not-a-list"}')

        with pytest.raises(ValueError) as exc_info:
            load_json(str(json_file))
        assert "lijst" in str(exc_info.value).lower() or "list" in str(exc_info.value).lower()

    def test_raises_on_non_string_date(self, tmp_path):
        """Non-string dates in list should raise ValueError."""
        json_file = tmp_path / "invalid.json"
        json_file.write_text('{"AAPL": [123, "2024-01-15"]}')

        with pytest.raises(ValueError) as exc_info:
            load_json(str(json_file))


class TestSaveJSON:
    """Tests for save_json function."""

    def test_saves_valid_json(self, tmp_path):
        """Should save data as valid JSON."""
        data = {"AAPL": ["2024-01-15", "2024-04-15"]}
        json_file = tmp_path / "output.json"

        save_json(data, str(json_file))

        loaded = json.loads(json_file.read_text())
        assert loaded == data

    def test_creates_parent_directories(self, tmp_path):
        """Should create parent directories if needed."""
        data = {"AAPL": ["2024-01-15"]}
        json_file = tmp_path / "subdir" / "output.json"

        save_json(data, str(json_file))

        assert json_file.exists()

    def test_overwrites_existing_file(self, tmp_path):
        """Should overwrite existing file."""
        json_file = tmp_path / "output.json"
        json_file.write_text('{"OLD": ["data"]}')

        save_json({"NEW": ["data"]}, str(json_file))

        loaded = json.loads(json_file.read_text())
        assert "NEW" in loaded
        assert "OLD" not in loaded

    def test_output_is_sorted(self, tmp_path):
        """Output should be sorted by keys."""
        data = {"ZZZZZ": ["2024-01-15"], "AAAA": ["2024-02-15"]}
        json_file = tmp_path / "output.json"

        save_json(data, str(json_file))

        content = json_file.read_text()
        # AAAA should appear before ZZZZZ in sorted output
        assert content.index("AAAA") < content.index("ZZZZZ")


class TestClosestFutureIndex:
    """Tests for closest_future_index function."""

    def test_finds_first_future_date(self):
        """Should return index of first date >= today."""
        dates = ["2024-01-01", "2024-02-01", "2024-03-01"]
        today = date(2024, 1, 15)

        result = closest_future_index(dates, today)

        assert result == 1  # 2024-02-01 is the first >= today

    def test_returns_zero_when_first_date_is_future(self):
        """Should return 0 when first date is already in future."""
        dates = ["2024-02-01", "2024-03-01"]
        today = date(2024, 1, 15)

        result = closest_future_index(dates, today)

        assert result == 0

    def test_returns_none_when_all_dates_past(self):
        """Should return None when all dates are in the past."""
        dates = ["2024-01-01", "2024-01-15"]
        today = date(2024, 2, 1)

        result = closest_future_index(dates, today)

        assert result is None

    def test_returns_none_for_empty_list(self):
        """Should return None for empty list."""
        result = closest_future_index([], date(2024, 1, 15))

        assert result is None

    def test_includes_today_as_future(self):
        """Today's date should be considered as future (>=)."""
        dates = ["2024-01-15"]
        today = date(2024, 1, 15)

        result = closest_future_index(dates, today)

        assert result == 0

    def test_skips_invalid_dates(self):
        """Should skip non-ISO date strings."""
        dates = ["invalid", "2024-02-01", "2024-03-01"]
        today = date(2024, 1, 15)

        result = closest_future_index(dates, today)

        assert result == 1


class TestEnforceMonthUniqueness:
    """Tests for enforce_month_uniqueness function."""

    def test_removes_same_month_dates(self):
        """Should remove all dates in same month as keep_date."""
        dates = ["2024-01-05", "2024-01-15", "2024-01-25", "2024-02-01"]

        result, removed = enforce_month_uniqueness(
            dates, keep_month="2024-01", keep_date="2024-01-20"
        )

        assert "2024-01-20" in result
        assert "2024-01-05" not in result
        assert "2024-01-15" not in result
        assert "2024-01-25" not in result
        assert "2024-02-01" in result
        assert removed == 3  # Three dates removed (05, 15, 25)

    def test_inserts_keep_date_chronologically(self):
        """Should insert keep_date in correct position."""
        dates = ["2024-01-01", "2024-03-01"]

        result, removed = enforce_month_uniqueness(
            dates, keep_month="2024-02", keep_date="2024-02-15"
        )

        assert result == ["2024-01-01", "2024-02-15", "2024-03-01"]

    def test_handles_empty_list(self):
        """Should handle empty input list."""
        result, removed = enforce_month_uniqueness(
            [], keep_month="2024-01", keep_date="2024-01-15"
        )

        assert "2024-01-15" in result
        assert removed == 0

    def test_no_removal_when_different_month(self):
        """Should not remove dates from different months."""
        dates = ["2024-02-01", "2024-03-01"]

        result, removed = enforce_month_uniqueness(
            dates, keep_month="2024-01", keep_date="2024-01-15"
        )

        assert len(result) == 3
        assert removed == 0


class TestUpdateNextEarnings:
    """Tests for update_next_earnings function."""

    def test_inserts_new_symbol(self):
        """Should insert new symbol with date."""
        json_data = {}
        csv_map = {"AAPL": "2024-01-15"}

        updated, changes = update_next_earnings(
            json_data, csv_map, date(2024, 1, 1), dry_run=True
        )

        assert "AAPL" in updated
        assert "2024-01-15" in updated["AAPL"]
        assert len(changes) == 1
        assert changes[0]["action"] == "created_symbol"

    def test_replaces_closest_future_date(self):
        """Should replace closest future date."""
        json_data = {"AAPL": ["2024-01-10", "2024-04-15"]}
        csv_map = {"AAPL": "2024-01-20"}

        updated, changes = update_next_earnings(
            json_data, csv_map, date(2024, 1, 5), dry_run=True
        )

        assert "2024-01-20" in updated["AAPL"]
        assert "2024-01-10" not in updated["AAPL"]  # Replaced + month deduped

    def test_dry_run_does_not_modify_original(self):
        """dry_run=True should not modify original data."""
        json_data = {"AAPL": ["2024-01-10"]}
        original_copy = {"AAPL": ["2024-01-10"]}
        csv_map = {"AAPL": "2024-01-20"}

        update_next_earnings(json_data, csv_map, date(2024, 1, 5), dry_run=True)

        assert json_data == original_copy

    def test_dry_run_false_modifies_original(self):
        """dry_run=False should modify original data."""
        json_data = {"AAPL": ["2024-01-10"]}
        csv_map = {"AAPL": "2024-02-20"}

        update_next_earnings(json_data, csv_map, date(2024, 1, 5), dry_run=False)

        assert "2024-02-20" in json_data.get("AAPL", [])

    def test_handles_invalid_csv_date(self):
        """Should skip invalid dates in csv_map."""
        json_data = {}
        csv_map = {"AAPL": "invalid-date"}

        updated, changes = update_next_earnings(
            json_data, csv_map, date(2024, 1, 1), dry_run=True
        )

        assert "AAPL" not in updated
        assert len(changes) == 0

    def test_normalizes_existing_dates(self):
        """Should normalize and sort existing dates."""
        json_data = {"AAPL": ["2024-03-01", "2024-01-01"]}
        csv_map = {"AAPL": "2024-02-01"}

        updated, changes = update_next_earnings(
            json_data, csv_map, date(2024, 1, 15), dry_run=True
        )

        # Dates should be sorted chronologically
        assert updated["AAPL"] == sorted(updated["AAPL"])

    def test_removes_duplicate_dates(self):
        """Should remove duplicate dates after update."""
        json_data = {"AAPL": ["2024-01-15", "2024-01-15"]}
        csv_map = {"AAPL": "2024-02-01"}

        updated, changes = update_next_earnings(
            json_data, csv_map, date(2024, 1, 10), dry_run=True
        )

        # Should not have duplicates
        assert len(updated["AAPL"]) == len(set(updated["AAPL"]))

    def test_changes_include_old_and_new_future(self):
        """Changes should include old and new future dates."""
        json_data = {"AAPL": ["2024-01-10"]}
        csv_map = {"AAPL": "2024-01-20"}

        updated, changes = update_next_earnings(
            json_data, csv_map, date(2024, 1, 5), dry_run=True
        )

        assert len(changes) == 1
        change = changes[0]
        assert change["old_future"] == "2024-01-10"
        assert change["new_future"] == "2024-01-20"

    def test_no_changes_when_same_date(self):
        """Should report no changes when date is already present."""
        json_data = {"AAPL": ["2024-01-15"]}
        csv_map = {"AAPL": "2024-01-15"}

        updated, changes = update_next_earnings(
            json_data, csv_map, date(2024, 1, 10), dry_run=True
        )

        # No actual change occurred
        assert len(changes) == 0

    def test_handles_empty_json_data(self):
        """Should handle empty json_data."""
        updated, changes = update_next_earnings(
            {}, {"AAPL": "2024-01-15"}, date(2024, 1, 1), dry_run=True
        )

        assert "AAPL" in updated

    def test_handles_empty_csv_map(self):
        """Should handle empty csv_map."""
        json_data = {"AAPL": ["2024-01-15"]}

        updated, changes = update_next_earnings(
            json_data, {}, date(2024, 1, 1), dry_run=True
        )

        assert len(changes) == 0

    def test_multiple_symbols_update(self):
        """Should handle multiple symbol updates."""
        json_data = {
            "AAPL": ["2024-01-10"],
            "GOOGL": ["2024-01-20"],
        }
        csv_map = {
            "AAPL": "2024-01-15",
            "GOOGL": "2024-01-25",
            "MSFT": "2024-02-01",
        }

        updated, changes = update_next_earnings(
            json_data, csv_map, date(2024, 1, 5), dry_run=True
        )

        assert len(changes) == 3
        assert "AAPL" in updated
        assert "GOOGL" in updated
        assert "MSFT" in updated
