import json
import sqlite3
import subprocess
import sys

import pytest
from conftest import open_store

from perq import (
    Document,
    IndexFormatError,
    Query,
    QueryMatcher,
    RangeFilter,
    SQLiteStore,
    index,
)


def matches(store, text="alpha", values=None):
    return list(QueryMatcher(store).matches(Document.from_text(text, values=values)))


def test_rebuild_removes_old_terms_queries_and_filters(store):
    index([Query.from_text(1, "alpha"), Query.from_text(2, "gone")], store)
    index([Query.from_text(1, "beta", filters=[RangeFilter("price", gt=10)])], store)
    assert matches(store, "alpha", {"price": [20]}) == []
    assert matches(store, "gone", {"price": [20]}) == []
    assert matches(store, "beta", {"price": [20]}) == [1]
    assert matches(store, "beta") == []
    index([], store)
    assert matches(store, "beta", {"price": [20]}) == []
    assert list(store.queries()) == []


@pytest.mark.parametrize("failure", ["duplicate", "iterator", "invalid"])
def test_failed_input_keeps_previous_generation(store, failure):
    before = Query.from_text(1, "alpha", filters=[RangeFilter("price", gt=10)], metadata={"v": 1})
    index([before], store)

    def broken():
        yield Query.from_text(1, "beta", filters=[RangeFilter("price", lt=10)])
        if failure == "duplicate":
            yield Query.from_text(1, "gamma")
        elif failure == "invalid":
            yield {"id": 2}
        else:
            raise RuntimeError("interrupted input")

    with pytest.raises((ValueError, RuntimeError)):
        index(broken(), store)
    assert matches(store, "alpha", {"price": [5]}) == []
    assert matches(store, "alpha", {"price": [15]}) == [1]
    assert matches(store, "beta", {"price": [5]}) == []
    assert list(store.queries()) == [before]


@pytest.mark.parametrize("error", [OSError, KeyboardInterrupt])
def test_failure_during_storage_writes_rolls_back(store, error):
    index([Query.from_text(1, "alpha")], store)

    class BrokenBuild:
        def queries(self):
            yield 0, json.dumps(Query.from_text(2, "beta").to_dict())

        def postings(self):
            raise error("simulated failed write")

    with pytest.raises(error):
        store.replace(BrokenBuild())
    assert matches(store) == [1]
    assert matches(store, "beta") == []


def test_snapshot_survives_successful_replacement(backend, tmp_path):
    path = tmp_path / "index"
    with open_store(backend, path) as store:
        index([Query.from_text("old", "alpha")], store)
        with store.snapshot() as reader:
            if backend == "sqlite":
                with SQLiteStore(path) as writer:
                    index([Query.from_text("new", "beta")], writer)
            else:
                index([Query.from_text("new", "beta")], store)
            assert [q.query_id for q in reader.queries()] == ["old"]
            assert list(reader.read_posts("R", "alpha")) == [(0, 0)]
        assert matches(store, "beta") == ["new"]
        assert matches(store, "alpha") == []


def test_results_release_snapshot_before_yielding(store):
    index([Query.from_text(1, "alpha"), Query.from_text(2, "alpha")], store)
    result = QueryMatcher(store).matches(Document.from_text("alpha"))
    assert next(result) == 1
    index([Query.from_text(3, "alpha")], store)
    assert list(result) == [2]
    assert matches(store) == [3]


def test_persistence_and_read_only(backend, tmp_path):
    if backend == "memory":
        pytest.skip("MemoryStore intentionally has no file format")
    path = tmp_path / "index"
    with open_store(backend, path) as writer:
        index([Query.from_text("saved", "alpha", metadata={"nested": [1, True, None]})], writer)
    with open_store(backend, path, readmode=True) as reader:
        assert matches(reader) == ["saved"]
        assert next(reader.queries()).metadata == {"nested": [1, True, None]}
        with pytest.raises(PermissionError):
            index([], reader)
        assert matches(reader) == ["saved"]


def test_legacy_sqlite_rejected_without_overwriting(tmp_path):
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE qdata (qid INTEGER, payload BLOB)")
        conn.execute("INSERT INTO qdata VALUES (1, 'original')")
    with pytest.raises(IndexFormatError):
        SQLiteStore(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT payload FROM qdata").fetchone()[0] == "original"


def test_future_format_is_rejected(backend, tmp_path):
    if backend == "memory":
        pytest.skip("no persistent format")
    path = tmp_path / "index"
    with open_store(backend, path) as store:
        if backend == "sqlite":
            store.conn.execute("UPDATE metadata SET value=?", (b"future",))
        else:
            with store.env.begin(write=True) as txn:
                txn.put(b"!format", b"future")
    with pytest.raises(IndexFormatError):
        open_store(backend, path)


def test_lmdb_map_full_preserves_previous_index(tmp_path):
    lmdb = pytest.importorskip("lmdb")
    from perq import LMDBStore

    with LMDBStore(tmp_path / "small.lmdb", map_size=128 * 1024) as store:
        index([Query.from_text(1, "alpha")], store)
        with pytest.raises(lmdb.MapFullError):
            index([Query.from_text(2, "beta", metadata={"large": "x" * 200_000})], store)
        assert matches(store) == [1]


def test_build_temp_files_removed_on_failure(store, tmp_path):
    with pytest.raises(ValueError):
        index([Query.from_text(1, "a"), Query.from_text(1, "b")], store, temp_dir=tmp_path)
    assert not list(tmp_path.glob("perq-build-*"))


def test_read_snapshot_survives_replacement_in_another_process(backend, tmp_path):
    if backend == "memory":
        pytest.skip("in-memory indexes are process local")
    path = tmp_path / "shared-index"
    with open_store(backend, path) as store:
        index([Query.from_text("old", "alpha")], store)
        with store.snapshot() as reader:
            run = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "perq",
                    "build",
                    "--backend",
                    backend,
                    "--index",
                    str(path),
                ],
                input='{"id":"new","terms":[["beta"]]}\n',
                text=True,
                capture_output=True,
                timeout=20,
            )
            assert run.returncode == 0, run.stderr
            assert [q.query_id for q in reader.queries()] == ["old"]
            assert list(reader.read_posts("R", "alpha")) == [(0, 0)]
        assert matches(store, "beta") == ["new"]


def test_lmdb_hash_collision_fails_atomically(tmp_path, monkeypatch):
    pytest.importorskip("lmdb")
    from perq import LMDBStore, storage

    with LMDBStore(tmp_path / "collision") as store:
        index([Query.from_text(1, "alpha")], store)
        with monkeypatch.context() as patch:
            patch.setattr(storage, "_post_key", lambda prefix, term: prefix.encode() + b"x" * 32)
            with pytest.raises(ValueError, match="collision"):
                index([Query.from_text(2, "beta"), Query.from_text(3, "gamma")], store)
        assert matches(store) == [1]
