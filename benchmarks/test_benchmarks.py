from __future__ import annotations

import importlib.util
import random
from pathlib import Path

import pytest

pytest.importorskip("pytest_benchmark")

from psearch import Document, MemoryStore, Query, QueryMatcher, SQLiteStore, index
from psearch.pstorage import LMDBStore

TERM_VOCAB = 2_000
QUERY_COUNT = 1_000
LARGE_QUERY_COUNT = 10_000
DOC_COUNT = 250
SEED = 7


def _backend_factories(tmp_path):
    factories = {
        "memory": lambda: MemoryStore(),
        "sqlite": lambda: SQLiteStore(str(tmp_path / "benchmark.sqlite")),
    }
    if importlib.util.find_spec("lmdb") is not None:
        factories["lmdb"] = lambda: LMDBStore(str(tmp_path / "benchmark.lmdb"))
    return factories


def _make_queries(count=QUERY_COUNT, vocab=TERM_VOCAB, seed=SEED):
    rng = random.Random(seed)
    queries = []
    for query_id in range(count):
        clause_count = rng.randint(1, 4)
        clauses = []
        for _ in range(clause_count):
            width = rng.randint(1, 3)
            clauses.append(tuple(f"t{rng.randrange(vocab)}" for _ in range(width)))
        data = {}
        if rng.random() < 0.2:
            start = rng.randint(10, 100)
            data["filters"] = [("price", start, start + rng.randint(5, 50))]
        queries.append(Query(query_id, clauses, **data))
    return queries


def _make_documents(count=DOC_COUNT, vocab=TERM_VOCAB, seed=SEED + 1):
    rng = random.Random(seed)
    docs = []
    for _ in range(count):
        token_count = rng.randint(8, 30)
        tokens = [f"t{rng.randrange(vocab)}" for _ in range(token_count)]
        rangefilters = {}
        if rng.random() < 0.3:
            rangefilters["price"] = [float(rng.randint(0, 150))]
        docs.append(Document({"body": [tokens]}, rangefilters=rangefilters))
    return docs


def _benchmark_label(query_count):
    return f"{query_count}_queries"


@pytest.mark.benchmark
@pytest.mark.parametrize("backend", ["memory", "sqlite", "lmdb"])
@pytest.mark.parametrize("query_count", [QUERY_COUNT, LARGE_QUERY_COUNT])
def test_benchmark_index_queries(benchmark, backend, query_count, tmp_path):
    factories = _backend_factories(tmp_path)
    if backend not in factories:
        pytest.skip(f"{backend} backend is not available")
    queries = _make_queries(count=query_count)

    def run():
        store = factories[backend]()
        try:
            index(queries, store)
        finally:
            store.close()

    benchmark.group = f"index/{_benchmark_label(query_count)}"
    benchmark.extra_info["backend"] = backend
    benchmark.extra_info["query_count"] = query_count
    benchmark(run)


@pytest.mark.benchmark
@pytest.mark.parametrize("backend", ["memory", "sqlite", "lmdb"])
@pytest.mark.parametrize("query_count", [QUERY_COUNT, LARGE_QUERY_COUNT])
def test_benchmark_match_documents(benchmark, backend, query_count, tmp_path):
    factories = _backend_factories(tmp_path)
    if backend not in factories:
        pytest.skip(f"{backend} backend is not available")
    queries = _make_queries(count=query_count)
    documents = _make_documents()
    store = factories[backend]()
    index(queries, store)
    matcher = QueryMatcher(store)

    def run():
        total = 0
        for document in documents:
            total += len(list(matcher.matches(document)))
        return total

    benchmark.group = f"match/{_benchmark_label(query_count)}"
    benchmark.extra_info["backend"] = backend
    benchmark.extra_info["query_count"] = query_count
    try:
        benchmark(run)
    finally:
        store.close()


@pytest.mark.benchmark
@pytest.mark.parametrize("backend", ["sqlite", "lmdb"])
def test_benchmark_reopen_and_match(benchmark, backend, tmp_path):
    factories = _backend_factories(tmp_path)
    if backend not in factories:
        pytest.skip(f"{backend} backend is not available")

    db_paths = {
        "sqlite": tmp_path / "reopen.sqlite",
        "lmdb": tmp_path / "reopen.lmdb",
    }
    db_path = db_paths[backend]
    if backend == "sqlite":
        for suffix in ("", "-shm", "-wal"):
            path = Path(f"{db_path}{suffix}")
            path.unlink(missing_ok=True)
    else:
        db_path.unlink(missing_ok=True)

    queries = _make_queries()
    document = _make_documents(count=1)[0]
    writer = factories[backend]()
    try:
        index(queries, writer)
    finally:
        writer.close()

    def run():
        reader = factories[backend]()
        try:
            return len(list(QueryMatcher(reader).matches(document)))
        finally:
            reader.close()

    benchmark.group = "reopen"
    benchmark.extra_info["backend"] = backend
    benchmark(run)
