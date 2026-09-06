import importlib.util

import pytest

from perq import LMDBStore, MemoryStore, SQLiteStore

BACKENDS = ["memory", "sqlite", "lmdb"]


@pytest.fixture(params=BACKENDS)
def backend(request):
    if request.param == "lmdb" and importlib.util.find_spec("lmdb") is None:
        pytest.skip("install the lmdb extra to test this backend")
    return request.param


def open_store(backend, path, **kwargs):
    return {"memory": lambda *a, **kw: MemoryStore(), "sqlite": SQLiteStore, "lmdb": LMDBStore}[
        backend
    ](path, **kwargs)


@pytest.fixture
def store(backend, tmp_path):
    with open_store(backend, tmp_path / "index") as instance:
        yield instance
