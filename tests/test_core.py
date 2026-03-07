from __future__ import annotations

import importlib.util

import pytest

from psearch import Document, MemoryStore, Query, QueryMatcher, SQLiteStore, index
from psearch.pdump import recreate_queries
from psearch.pstorage import LMDBStore


def _backend_params():
    params = ["memory", "sqlite"]
    if importlib.util.find_spec("lmdb") is not None:
        params.append("lmdb")
    return params


@pytest.fixture(params=_backend_params())
def store(request, tmp_path):
    if request.param == "memory":
        instance = MemoryStore()
    elif request.param == "sqlite":
        instance = SQLiteStore(str(tmp_path / "index.sqlite"))
    else:
        instance = LMDBStore(str(tmp_path / "index.lmdb"))
    try:
        yield instance
    finally:
        instance.close()


def test_store_round_trip(store):
    store.write_posts("R", "alpha", [(1, 0), (2, 4)])
    store.write_posts("T", "beta", [(1, -2)])
    store.set_data(1, {"filters": [("price", 10, 20)]})

    assert list(store.read_posts("R", "alpha")) == [(1, 0), (2, 4)]
    assert list(store.read_posts("T", "beta")) == [(1, -2)]
    assert list(store.read_posts("R", "missing")) == []
    assert store.get_data(1) == {"filters": [("price", 10, 20)]}
    assert store.get_data(99, {"missing": True}) == {"missing": True}


def test_recreate_queries_from_index(store):
    queries = [
        Query(1, [("information",), ("retrieval",)]),
        Query(2, [("text", "data"), ("mining",)]),
    ]

    index(queries, store)

    assert list(recreate_queries(store)) == [
        (1, [["information"], ["retrieval"]]),
        (2, [["data", "text"], ["mining"]]),
    ]


def test_reindexing_same_sqlite_db_does_not_duplicate_postings(tmp_path):
    path = tmp_path / "index.sqlite"
    queries = [
        Query(1, [("alpha",), ("beta",)]),
        Query(2, [("beta",), ("gamma",)]),
    ]

    first = SQLiteStore(str(path))
    try:
        index(queries, first)
    finally:
        first.close()

    second = SQLiteStore(str(path))
    try:
        index(queries, second)
    finally:
        second.close()

    reader = SQLiteStore(str(path), readmode=True)
    try:
        assert list(recreate_queries(reader)) == [
            (1, [["alpha"], ["beta"]]),
            (2, [["beta"], ["gamma"]]),
        ]
        matcher = QueryMatcher(reader)
        assert list(matcher.matches(Document({"body": [["alpha", "beta"]]}))) == [1]
    finally:
        reader.close()


def test_reindexing_same_sqlite_db_with_modified_clause_positions(tmp_path):
    path = tmp_path / "index.sqlite"
    original_queries = [
        Query(1, [("alpha",), ("beta",)]),
        Query(2, [("beta",), ("gamma",)]),
    ]

    first = SQLiteStore(str(path))
    try:
        index(original_queries, first)
    finally:
        first.close()

    modified_queries = [
        Query(1, [("beta",), ("alpha",)]),
        Query(2, [("gamma",), ("beta",)]),
    ]

    second = SQLiteStore(str(path))
    try:
        index(modified_queries, second)
    finally:
        second.close()

    reader = SQLiteStore(str(path), readmode=True)
    try:
        assert list(recreate_queries(reader)) == [
            (1, [["beta"], ["alpha"]]),
            (2, [["gamma"], ["beta"]]),
        ]
        matcher = QueryMatcher(reader)
        assert list(matcher.matches(Document({"body": [["alpha", "beta"]]}))) == [1]
    finally:
        reader.close()


def test_matcher_handles_or_groups_and_filters(store):
    queries = [
        Query(1, [("information",), ("retrieval",)]),
        Query(2, [("text", "data"), ("mining",)], filters=[("price", 100, 200)]),
        Query(3, [("news",)]),
    ]
    index(queries, store)
    matcher = QueryMatcher(store)

    doc = Document(
        {"body": [["introduction", "to", "information", "retrieval"]]},
        rangefilters={"price": [30.0]},
    )
    assert list(matcher.matches(doc)) == [1]

    filtered = Document(
        {"body": [["text", "mining"]]},
        rangefilters={"price": [150.0]},
    )
    assert list(matcher.matches(filtered)) == [2]

    non_match = Document(
        {"body": [["data", "mining"]]},
        rangefilters={"price": [99.0]},
    )
    assert list(matcher.matches(non_match)) == []


def test_empty_index_and_missing_terms_return_no_matches(store):
    matcher = QueryMatcher(store)

    assert list(matcher.matches(Document({"body": [["alpha"]]}))) == []

    index([Query(1, [("known",)])], store)

    assert list(matcher.matches(Document({"body": [["unknown"]]}))) == []


def test_duplicate_terms_in_documents_and_queries_do_not_change_matches(store):
    queries = [
        Query(1, [("alpha", "alpha"), ("beta",)]),
        Query(2, [("alpha",), ("gamma",)]),
    ]
    index(queries, store)
    matcher = QueryMatcher(store)

    doc = Document({"body": [["alpha", "alpha", "beta", "beta"]]})

    assert list(matcher.matches(doc)) == [1]


def test_range_filter_requires_present_matching_value(store):
    index(
        [
            Query(1, [("alpha",)], filters=[("price", 10, 20)]),
            Query(2, [("alpha",)], filters=[("price", 20, None)]),
        ],
        store,
    )
    matcher = QueryMatcher(store)

    assert list(matcher.matches(Document({"body": [["alpha"]]}))) == []
    assert list(
        matcher.matches(
            Document({"body": [["alpha"]]}, rangefilters={"price": [10.0, 15.0]})
        )
    ) == [1]
    assert list(
        matcher.matches(
            Document({"body": [["alpha"]]}, rangefilters={"price": [25.0]})
        )
    ) == [2]


def test_store_overwrites_query_data_for_same_id(store):
    store.set_data(7, {"version": 1})
    store.set_data(7, {"version": 2})

    assert store.get_data(7) == {"version": 2}


def test_recreate_queries_ignores_missing_postings(store):
    assert list(recreate_queries(store)) == []


def test_document_termfreq_and_length():
    doc = Document({"title": [["a", "b"], ["a"]], "body": [["c", "a"]]})

    termfreqs, doclen = doc.termfreq_and_length("title", "body")

    assert termfreqs == {"a": 3, "b": 1, "c": 1}
    assert doclen == 5


def test_index_rejects_queries_over_term_limit():
    store = MemoryStore()
    try:
        too_long = Query(1, [(str(i),) for i in range(32)])
        with pytest.raises(ValueError):
            index([too_long], store)
    finally:
        store.close()


def test_sqlite_persists_across_reopen(tmp_path):
    path = tmp_path / "index.sqlite"
    writer = SQLiteStore(str(path))
    try:
        index([Query(10, [("alpha",), ("beta",)])], writer)
    finally:
        writer.close()

    reader = SQLiteStore(str(path), readmode=True)
    try:
        matcher = QueryMatcher(reader)
        assert list(matcher.matches(Document({"body": [["alpha", "beta"]]}))) == [10]
    finally:
        reader.close()


def test_lmdb_persists_across_reopen_when_available(tmp_path):
    if importlib.util.find_spec("lmdb") is None:
        pytest.skip("lmdb is not installed")

    path = tmp_path / "index.lmdb"
    writer = LMDBStore(str(path))
    try:
        index([Query(20, [("alpha",), ("beta",)])], writer)
    finally:
        writer.close()

    reader = LMDBStore(str(path), readmode=True)
    try:
        matcher = QueryMatcher(reader)
        assert list(matcher.matches(Document({"body": [["alpha", "beta"]]}))) == [20]
        assert list(recreate_queries(reader)) == [(20, [["alpha"], ["beta"]])]
    finally:
        reader.close()


def test_lmdb_round_trips_terms_with_separator_char(tmp_path):
    if importlib.util.find_spec("lmdb") is None:
        pytest.skip("lmdb is not installed")

    path = tmp_path / "separator.lmdb"
    term = "alpha\x1fbeta"
    writer = LMDBStore(str(path))
    try:
        index([Query(30, [(term,), ("gamma",)])], writer)
    finally:
        writer.close()

    reader = LMDBStore(str(path), readmode=True)
    try:
        assert list(recreate_queries(reader)) == [(30, [[term], ["gamma"]])]
        matcher = QueryMatcher(reader)
        assert list(matcher.matches(Document({"body": [[term, "gamma"]]}))) == [30]
    finally:
        reader.close()
