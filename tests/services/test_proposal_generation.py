"""Tests voor proposal_generation module."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from tomic.services.proposal_generation import (
    ProposalGenerationError,
    ProposalGenerationResult,
    _load_metrics_from_file,
    _load_positions,
    generate_proposal_overview,
)


@pytest.fixture
def sample_positions():
    """Return sample positions list."""
    return [
        {
            "symbol": "AAPL",
            "strategy": "IronCondor",
            "quantity": 1,
            "status": "open",
        },
        {
            "symbol": "MSFT",
            "strategy": "CreditSpread",
            "quantity": 2,
            "status": "open",
        },
    ]


@pytest.fixture
def sample_metrics():
    """Return sample metrics dict."""
    return {
        "AAPL": {
            "iv": 0.35,
            "hv20": 0.30,
            "iv_rank": 65.0,
            "iv_percentile": 70.0,
        },
        "MSFT": {
            "iv": 0.28,
            "hv20": 0.25,
            "iv_rank": 50.0,
            "iv_percentile": 55.0,
        },
    }


class TestLoadPositions:
    """Tests voor _load_positions functie."""

    def test_load_positions_with_valid_file(self, tmp_path, sample_positions):
        """Test _load_positions met geldig bestand."""
        positions_file = tmp_path / "positions.json"
        positions_file.write_text(json.dumps(sample_positions))

        result = _load_positions(positions_file)

        assert list(result) == sample_positions

    def test_load_positions_with_empty_file(self, tmp_path):
        """Test _load_positions met leeg bestand."""
        positions_file = tmp_path / "positions.json"
        positions_file.write_text("[]")

        result = _load_positions(positions_file)

        assert list(result) == []

    def test_load_positions_with_invalid_json(self, tmp_path):
        """Test _load_positions met ongeldige JSON."""
        positions_file = tmp_path / "positions.json"
        positions_file.write_text("{ invalid json }")

        with pytest.raises(json.JSONDecodeError):
            _load_positions(positions_file)

    def test_load_positions_with_non_list(self, tmp_path):
        """Test _load_positions met niet-lijst JSON."""
        positions_file = tmp_path / "positions.json"
        positions_file.write_text('{"not": "a list"}')

        with pytest.raises(ProposalGenerationError, match="geen lijst"):
            _load_positions(positions_file)

    def test_load_positions_with_missing_file(self, tmp_path):
        """Test _load_positions met ontbrekend bestand."""
        positions_file = tmp_path / "nonexistent.json"

        with pytest.raises(FileNotFoundError):
            _load_positions(positions_file)


class TestLoadMetricsFromFile:
    """Tests voor _load_metrics_from_file functie."""

    def test_load_metrics_from_file_with_valid_data(self, tmp_path, sample_metrics):
        """Test _load_metrics_from_file met geldige data."""
        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(json.dumps(sample_metrics))

        result = _load_metrics_from_file(metrics_file)

        assert isinstance(result, dict)
        assert "AAPL" in result
        assert "MSFT" in result
        # Values moeten SimpleNamespace objecten zijn
        assert isinstance(result["AAPL"], SimpleNamespace)
        assert result["AAPL"].iv == 0.35
        assert result["MSFT"].hv20 == 0.25

    def test_load_metrics_from_file_with_empty_dict(self, tmp_path):
        """Test _load_metrics_from_file met lege dict."""
        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text("{}")

        result = _load_metrics_from_file(metrics_file)

        assert result == {}

    def test_load_metrics_from_file_with_invalid_json(self, tmp_path):
        """Test _load_metrics_from_file met ongeldige JSON."""
        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text("{ invalid json }")

        with pytest.raises(json.JSONDecodeError):
            _load_metrics_from_file(metrics_file)

    def test_load_metrics_from_file_with_non_dict(self, tmp_path):
        """Test _load_metrics_from_file met niet-dict JSON."""
        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text('["not", "a", "dict"]')

        with pytest.raises(ProposalGenerationError, match="geen object"):
            _load_metrics_from_file(metrics_file)


class TestGenerateProposalOverview:
    """Tests voor generate_proposal_overview functie."""

    def test_generate_proposal_overview_with_valid_positions(
        self, tmp_path, sample_positions, sample_metrics
    ):
        """Test generate_proposal_overview met geldige posities."""
        positions_file = tmp_path / "positions.json"
        positions_file.write_text(json.dumps(sample_positions))
        export_dir = tmp_path / "exports"
        export_dir.mkdir()

        # Mock generate_proposals
        mock_proposals = {
            "AAPL": [
                {
                    "strategy": "IronCondor",
                    "score": 85.0,
                    "ev": 125.0,
                }
            ],
            "MSFT": [
                {
                    "strategy": "CreditSpread",
                    "score": 78.0,
                    "ev": 95.0,
                }
            ],
        }

        with patch("tomic.services.proposal_generation.generate_proposals") as mock_gen:
            mock_gen.return_value = mock_proposals

            with patch("tomic.services.proposal_generation.load_latest_summaries") as mock_metrics:
                mock_metrics.return_value = sample_metrics

                result = generate_proposal_overview(
                    positions_path=positions_file,
                    export_dir=export_dir,
                )

        assert isinstance(result, ProposalGenerationResult)
        assert result.proposals == mock_proposals
        assert result.metrics == sample_metrics
        assert len(result.warnings) == 0

    def test_generate_proposal_overview_with_missing_positions_file(self, tmp_path):
        """Test generate_proposal_overview met ontbrekend posities bestand."""
        positions_file = tmp_path / "nonexistent.json"

        with pytest.raises(ProposalGenerationError, match="Positions file not found"):
            generate_proposal_overview(positions_path=positions_file)

    def test_generate_proposal_overview_with_empty_positions(self, tmp_path):
        """Test generate_proposal_overview met lege posities."""
        positions_file = tmp_path / "positions.json"
        positions_file.write_text("[]")
        export_dir = tmp_path / "exports"
        export_dir.mkdir()

        with patch("tomic.services.proposal_generation.generate_proposals") as mock_gen:
            mock_gen.return_value = {}

            with patch("tomic.services.proposal_generation.load_latest_summaries") as mock_metrics:
                mock_metrics.return_value = {}

                result = generate_proposal_overview(
                    positions_path=positions_file,
                    export_dir=export_dir,
                )

        assert isinstance(result, ProposalGenerationResult)
        assert result.proposals == {}
        assert len(result.warnings) == 0

    def test_generate_proposal_overview_with_missing_metrics(
        self, tmp_path, sample_positions
    ):
        """Test generate_proposal_overview met ontbrekende metrics."""
        positions_file = tmp_path / "positions.json"
        positions_file.write_text(json.dumps(sample_positions))
        export_dir = tmp_path / "exports"
        export_dir.mkdir()

        mock_proposals = {
            "AAPL": [{"strategy": "IronCondor", "score": 85.0}],
        }

        with patch("tomic.services.proposal_generation.generate_proposals") as mock_gen:
            mock_gen.return_value = mock_proposals

            with patch("tomic.services.proposal_generation.load_latest_summaries") as mock_metrics:
                # Simuleer exception bij laden van metrics
                mock_metrics.side_effect = Exception("Metrics niet beschikbaar")

                result = generate_proposal_overview(
                    positions_path=positions_file,
                    export_dir=export_dir,
                )

        assert isinstance(result, ProposalGenerationResult)
        assert result.proposals == mock_proposals
        assert result.metrics is None
        # Er moet een waarschuwing zijn over ontbrekende metrics
        assert len(result.warnings) > 0
        assert any("Volatiliteitsdata" in w for w in result.warnings)

    def test_generate_proposal_overview_with_metrics_file(
        self, tmp_path, sample_positions, sample_metrics
    ):
        """Test generate_proposal_overview met expliciete metrics file."""
        positions_file = tmp_path / "positions.json"
        positions_file.write_text(json.dumps(sample_positions))
        export_dir = tmp_path / "exports"
        export_dir.mkdir()
        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(json.dumps(sample_metrics))

        mock_proposals = {
            "AAPL": [{"strategy": "IronCondor", "score": 85.0}],
        }

        with patch("tomic.services.proposal_generation.generate_proposals") as mock_gen:
            mock_gen.return_value = mock_proposals

            result = generate_proposal_overview(
                positions_path=positions_file,
                export_dir=export_dir,
                metrics_path=metrics_file,
            )

        assert isinstance(result, ProposalGenerationResult)
        assert result.proposals == mock_proposals
        assert result.metrics is not None
        assert "AAPL" in result.metrics
        assert len(result.warnings) == 0

    def test_generate_proposal_overview_with_missing_metrics_file(
        self, tmp_path, sample_positions
    ):
        """Test generate_proposal_overview met ontbrekende metrics file."""
        positions_file = tmp_path / "positions.json"
        positions_file.write_text(json.dumps(sample_positions))
        export_dir = tmp_path / "exports"
        export_dir.mkdir()
        metrics_file = tmp_path / "nonexistent_metrics.json"

        mock_proposals = {
            "AAPL": [{"strategy": "IronCondor", "score": 85.0}],
        }

        with patch("tomic.services.proposal_generation.generate_proposals") as mock_gen:
            mock_gen.return_value = mock_proposals

            result = generate_proposal_overview(
                positions_path=positions_file,
                export_dir=export_dir,
                metrics_path=metrics_file,
            )

        assert isinstance(result, ProposalGenerationResult)
        assert result.proposals == mock_proposals
        assert result.metrics is None
        # Er moet een waarschuwing zijn over ontbrekende metrics file
        assert len(result.warnings) > 0
        assert any("Metrics file not found" in w for w in result.warnings)

    def test_generate_proposal_overview_with_corrupt_metrics_file(
        self, tmp_path, sample_positions
    ):
        """Test generate_proposal_overview met corrupte metrics file."""
        positions_file = tmp_path / "positions.json"
        positions_file.write_text(json.dumps(sample_positions))
        export_dir = tmp_path / "exports"
        export_dir.mkdir()
        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text("{ invalid json }")

        mock_proposals = {
            "AAPL": [{"strategy": "IronCondor", "score": 85.0}],
        }

        with patch("tomic.services.proposal_generation.generate_proposals") as mock_gen:
            mock_gen.return_value = mock_proposals

            result = generate_proposal_overview(
                positions_path=positions_file,
                export_dir=export_dir,
                metrics_path=metrics_file,
            )

        assert isinstance(result, ProposalGenerationResult)
        assert result.proposals == mock_proposals
        assert result.metrics is None
        # Er moet een waarschuwing zijn over het niet kunnen laden van metrics
        assert len(result.warnings) > 0
        assert any("Kan metrics niet laden" in w for w in result.warnings)

    def test_generate_proposal_overview_uses_default_paths(self, tmp_path, sample_positions):
        """Test dat generate_proposal_overview default paths uit config gebruikt."""
        # Maak een positions file
        positions_file = tmp_path / "positions.json"
        positions_file.write_text(json.dumps(sample_positions))

        mock_proposals = {
            "AAPL": [{"strategy": "IronCondor", "score": 85.0}],
        }

        with patch("tomic.services.proposal_generation.cfg_get") as mock_cfg:
            # Mock de config getter
            mock_cfg.side_effect = lambda key, default: {
                "POSITIONS_FILE": str(positions_file),
                "EXPORT_DIR": str(tmp_path / "exports"),
            }.get(key, default)

            with patch("tomic.services.proposal_generation.generate_proposals") as mock_gen:
                mock_gen.return_value = mock_proposals

                with patch("tomic.services.proposal_generation.load_latest_summaries") as mock_metrics:
                    mock_metrics.return_value = {}

                    # Roep aan zonder parameters
                    result = generate_proposal_overview()

        assert isinstance(result, ProposalGenerationResult)
        assert result.proposals == mock_proposals

    def test_generate_proposal_overview_returns_empty_proposals_on_none(
        self, tmp_path, sample_positions
    ):
        """Test dat generate_proposal_overview {} teruggeeft als generate_proposals None returnt."""
        positions_file = tmp_path / "positions.json"
        positions_file.write_text(json.dumps(sample_positions))
        export_dir = tmp_path / "exports"
        export_dir.mkdir()

        with patch("tomic.services.proposal_generation.generate_proposals") as mock_gen:
            # generate_proposals kan None returnen
            mock_gen.return_value = None

            with patch("tomic.services.proposal_generation.load_latest_summaries") as mock_metrics:
                mock_metrics.return_value = {}

                result = generate_proposal_overview(
                    positions_path=positions_file,
                    export_dir=export_dir,
                )

        assert isinstance(result, ProposalGenerationResult)
        # None moet worden omgezet naar {}
        assert result.proposals == {}

    def test_generate_proposal_overview_extracts_symbols_from_positions(
        self, tmp_path, sample_positions
    ):
        """Test dat generate_proposal_overview symbols uit positions extraheert."""
        positions_file = tmp_path / "positions.json"
        positions_file.write_text(json.dumps(sample_positions))
        export_dir = tmp_path / "exports"
        export_dir.mkdir()

        captured_symbols = None

        def capture_symbols(symbols):
            nonlocal captured_symbols
            captured_symbols = set(symbols)
            return {}

        with patch("tomic.services.proposal_generation.generate_proposals") as mock_gen:
            mock_gen.return_value = {}

            with patch("tomic.services.proposal_generation.load_latest_summaries") as mock_metrics:
                mock_metrics.side_effect = capture_symbols

                result = generate_proposal_overview(
                    positions_path=positions_file,
                    export_dir=export_dir,
                )

        # Moet AAPL en MSFT uit sample_positions hebben geëxtraheerd
        assert captured_symbols == {"AAPL", "MSFT"}

    def test_generate_proposal_overview_handles_positions_without_symbol(
        self, tmp_path
    ):
        """Test dat generate_proposal_overview positions zonder symbol overslaat."""
        positions = [
            {"symbol": "AAPL", "strategy": "IronCondor"},
            {"strategy": "CreditSpread"},  # geen symbol
            {"symbol": "MSFT", "strategy": "Strangle"},
        ]

        positions_file = tmp_path / "positions.json"
        positions_file.write_text(json.dumps(positions))
        export_dir = tmp_path / "exports"
        export_dir.mkdir()

        captured_symbols = None

        def capture_symbols(symbols):
            nonlocal captured_symbols
            captured_symbols = set(symbols)
            return {}

        with patch("tomic.services.proposal_generation.generate_proposals") as mock_gen:
            mock_gen.return_value = {}

            with patch("tomic.services.proposal_generation.load_latest_summaries") as mock_metrics:
                mock_metrics.side_effect = capture_symbols

                result = generate_proposal_overview(
                    positions_path=positions_file,
                    export_dir=export_dir,
                )

        # Moet alleen AAPL en MSFT hebben, niet None
        assert captured_symbols == {"AAPL", "MSFT"}
        assert None not in captured_symbols
