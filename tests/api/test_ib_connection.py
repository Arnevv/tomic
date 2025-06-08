def test_connection():
    import importlib, sys
    sys.modules.pop("tomic.api.ib_connection", None)
    connect_ib = importlib.import_module("tomic.api.ib_connection").connect_ib
    try:
        app = connect_ib()
        assert app.next_valid_id is not None
        app.disconnect()
    except Exception as e:
        assert "kon niet verbinden" in str(e).lower() or isinstance(e, TimeoutError)
