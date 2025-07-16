import importlib
import os

def test_ibapi_imports():
    """Controleert of ibapi componenten beschikbaar zijn"""
    assert importlib.util.find_spec("tomic.ibapi.client"), "client.py ontbreekt"
    assert importlib.util.find_spec("tomic.ibapi.wrapper"), "wrapper.py ontbreekt"
    assert importlib.util.find_spec("tomic.ibapi.protobuf.OpenOrder_pb2"), "OpenOrder_pb2 ontbreekt"

def test_required_packages():
    """Check of vereiste packages geïnstalleerd zijn"""
    import google.protobuf
    import pandas
    import numpy
    import requests

def test_config_files():
    """Check of basisdata aanwezig is"""
    expected = [
        "account_info.example.json",
        "positions.example.json",
        "portfolio_meta.json",
    ]
    root = os.path.dirname(os.path.dirname(__file__))
    for fname in expected:
        fpath = os.path.join(root, "tomic", "data", fname)
        assert os.path.exists(fpath), f"{fname} ontbreekt in tomic/data/"

