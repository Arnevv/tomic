from __future__ import annotations

from pathlib import Path

import pytest

from tomic.services.chain_sources import (
    ChainSourceDecision,
    ChainSourceError,
    PolygonFileAdapter,
    TwsLiveAdapter,
    resolve_chain_source,
)


def test_polygon_adapter_prefers_existing_dir(tmp_path):
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    existing_dir = tmp_path / "existing"
    existing_dir.mkdir()
    existing_file = existing_dir / "AAA_1-optionchainpolygon.csv"
    existing_file.write_text("data")

    adapter = PolygonFileAdapter(export_dir=export_dir)
    decision = adapter.acquire("AAA", existing_dir=existing_dir)

    assert isinstance(decision, ChainSourceDecision)
    assert decision.path == existing_file
    assert decision.source == "polygon"
    assert decision.source_provenance == str(existing_file)


def test_polygon_adapter_fetches_when_missing(tmp_path):
    export_dir = tmp_path / "exports"
    export_dir.mkdir()

    created: list[Path] = []

    def fake_fetch(symbol: str) -> None:
        target = export_dir / f"{symbol}_fetched-optionchainpolygon.csv"
        target.write_text("content")
        created.append(target)

    adapter = PolygonFileAdapter(export_dir=export_dir, fetcher=fake_fetch)
    decision = adapter.acquire("BBB")

    assert created, "fetcher should be invoked"
    assert decision.path == created[0]


def test_polygon_adapter_missing_raises(tmp_path):
    adapter = PolygonFileAdapter(export_dir=tmp_path)
    with pytest.raises(ChainSourceError) as exc:
        adapter.acquire("CCC")
    assert "Geen Polygon-chain" in str(exc.value)


def test_tws_adapter_success(tmp_path):
    target = tmp_path / "tws.csv"
    target.write_text("data")

    adapter = TwsLiveAdapter(exporter=lambda symbol: target, schema_version="tws.v1")
    decision = adapter.acquire("DDD")

    assert decision.path == target
    assert decision.schema_version == "tws.v1"
    assert decision.source == "tws"


def test_tws_adapter_failure():
    adapter = TwsLiveAdapter(exporter=lambda symbol: None)
    with pytest.raises(ChainSourceError) as exc:
        adapter.acquire("EEE")
    assert "TWS-chain" in str(exc.value)


def test_resolve_chain_source_routes(tmp_path):
    polygon_target = tmp_path / "FFF_20240101-optionchainpolygon.csv"
    polygon_target.write_text("poly")
    tws_target = tmp_path / "tws.csv"
    tws_target.write_text("tws")

    polygon = PolygonFileAdapter(export_dir=tmp_path)
    tws = TwsLiveAdapter(exporter=lambda symbol: tws_target)

    decision_poly = resolve_chain_source(
        "FFF", source="polygon", polygon=polygon, tws=tws
    )
    assert decision_poly.path == polygon_target  # polygon_target should exist via search

    decision_tws = resolve_chain_source("GGG", source="tws", polygon=polygon, tws=tws)
    assert decision_tws.path == tws_target
