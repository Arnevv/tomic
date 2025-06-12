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
