"""Test package initialization with minimal dependency stubs."""

import sys
import types

# Provide a lightweight aiohttp stub so modules import correctly
aiohttp_stub = types.ModuleType("aiohttp")
aiohttp_stub.ClientError = Exception
aiohttp_stub.ClientTimeout = lambda total=None: types.SimpleNamespace(total=total)
class _DummySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def get(self, *a, **k):
        class _Resp:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                pass

            async def json(self):
                return {}

            async def text(self):
                return ""

            def raise_for_status(self):
                pass

        return _Resp()

aiohttp_stub.ClientSession = lambda *a, **k: _DummySession()
sys.modules.setdefault("aiohttp", aiohttp_stub)

# Minimal pandas/numpy stubs for environments without these packages
pandas_stub = types.ModuleType("pandas")
pandas_stub.DataFrame = object
pandas_stub.concat = lambda frames, ignore_index=False: object()
pandas_stub.Series = object
sys.modules.setdefault("pandas", pandas_stub)

numpy_stub = types.ModuleType("numpy")
numpy_stub.nan = float('nan')
sys.modules.setdefault("numpy", numpy_stub)

scipy_stub = types.ModuleType("scipy")
interpolate_stub = types.ModuleType("scipy.interpolate")

def _dummy_spline(x, y, s=0):
    class _S:
        def __call__(self, new_x):
            return [y[0] for _ in new_x]
    return _S()

interpolate_stub.UnivariateSpline = _dummy_spline
scipy_stub.interpolate = interpolate_stub
sys.modules.setdefault("scipy", scipy_stub)
sys.modules.setdefault("scipy.interpolate", interpolate_stub)
