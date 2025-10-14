"""Tests for the option chain quality scoring helpers."""

from __future__ import annotations

import math
from typing import Iterable, Iterator, Tuple

from tomic.helpers.quality_check import calculate_csv_quality


class FakeDataFrame:
    """Minimal stand-in mimicking the parts of pandas used by the scorer."""

    def __init__(self, rows: Iterable[dict]):
        self._rows = [dict(row) for row in rows]

    def __len__(self) -> int:
        return len(self._rows)

    def iterrows(self) -> Iterator[Tuple[int, dict]]:
        for idx, row in enumerate(self._rows):
            yield idx, row

    @property
    def empty(self) -> bool:
        return not self._rows


def _build_df(rows: Iterable[dict]) -> FakeDataFrame:
    return FakeDataFrame(rows)


def test_calculate_csv_quality_perfect_score() -> None:
    df = _build_df(
        [
            {
                "bid": 1.0,
                "ask": 1.2,
                "iv": 0.4,
                "delta": 0.3,
                "gamma": 0.02,
                "vega": 0.6,
                "theta": -0.01,
            },
            {
                "bid": 2.0,
                "ask": 2.3,
                "iv": 0.5,
                "delta": -0.4,
                "gamma": 0.03,
                "vega": 0.7,
                "theta": -0.02,
            },
        ]
    )

    score = calculate_csv_quality(df)

    assert math.isclose(score, 100.0)


def test_calculate_csv_quality_flags_bad_spread() -> None:
    df = _build_df(
        [
            {
                "bid": 1.0,
                "ask": 3.0,  # very wide spread
                "iv": 0.4,
                "delta": 0.3,
                "gamma": 0.02,
                "vega": 0.6,
                "theta": -0.01,
            }
        ]
    )

    score = calculate_csv_quality(df)

    # Coverage and Greeks pass (40% + 20%), pricing fails -> 60 score.
    assert math.isclose(score, 60.0)


def test_calculate_csv_quality_partial_greek_failure() -> None:
    df = _build_df(
        [
            {
                "bid": 1.0,
                "ask": 1.1,
                "iv": 0.4,
                "delta": 0.3,
                "gamma": 0.02,
                "vega": 0.6,
                "theta": -0.01,
            },
            {
                "bid": 1.5,
                "ask": 1.7,
                "iv": 0.6,
                "delta": 1.5,  # invalid delta
                "gamma": 0.02,
                "vega": 0.6,
                "theta": -0.01,
            },
        ]
    )

    score = calculate_csv_quality(df)

    # Greeks score drops to 50%, the rest remains 100%.
    assert math.isclose(score, 90.0)
