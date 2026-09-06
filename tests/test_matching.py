import random

import pytest

from perq import Document, Query, QueryMatcher, RangeFilter, index, tokenize


def match(store, text="", values=None):
    return list(QueryMatcher(store).matches(Document.from_text(text, values=values)))


def test_boolean_groups_filters_and_order(store):
    queries = [
        Query(
            "first",
            [("text", "data"), ("mining",)],
            filters=[RangeFilter("price", gte=100, lt=200)],
        ),
        Query(2**80, [("mining",)]),
    ]
    index(queries, store)
    assert match(store, "DATA mining", {"price": [100]}) == ["first", 2**80]
    assert match(store, "data mining", {"price": [200]}) == [2**80]
    assert match(store, "data", {"price": [150]}) == []
    assert match(store, "mining") == [2**80]
    assert list(store.queries()) == queries


def test_empty_index_and_documents(store):
    assert match(store, "alpha") == []
    index([Query.from_text(1, "alpha")], store)
    assert match(store) == []


def test_repeated_terms_and_overlapping_clauses(store):
    index([Query(1, [("a", "a", "b"), ("a", "c"), ("c",)])], store)
    assert match(store, "a a c c") == [1]
    assert match(store, "b c") == [1]
    assert match(store, "a b") == []


def test_filter_only_queries_and_missing_values(store):
    index([Query("numeric", filters=[RangeFilter("price", gte=10, lte=20)])], store)
    assert match(store, values={"price": [10, 50]}) == ["numeric"]
    assert match(store, values={"price": [20]}) == ["numeric"]
    assert match(store, values={"price": [9, 21]}) == []
    assert match(store) == []


def test_sixty_four_clauses_and_last_bit(store):
    terms = [f"t{i}" for i in range(64)]
    index([Query(1, [(t,) for t in terms])], store)
    assert list(QueryMatcher(store).matches(Document(terms))) == [1]
    for missing in (0, 31, 63):
        assert (
            list(QueryMatcher(store).matches(Document(terms[:missing] + terms[missing + 1 :])))
            == []
        )


def test_unicode_long_and_separator_terms(store):
    terms = ["雪" * 1000, "alpha\x1fbeta", "null\0byte"]
    index([Query("unicode", [terms])], store)
    for term in terms:
        assert list(QueryMatcher(store).matches(Document([term]))) == ["unicode"]


def test_integer_and_string_ids_are_distinct_and_stable(store):
    ids = ["z", 1, "1", -(2**80), "a"]
    index([Query.from_text(qid, "alpha") for qid in ids], store)
    assert match(store, "alpha") == ids


@pytest.mark.parametrize("seed", range(5))
def test_randomized_matches_agree_with_independent_reference(store, seed):
    rng = random.Random(seed)
    vocabulary = [f"t{i}" for i in range(20)]
    queries = []
    for qid in range(150):
        clauses = [rng.choices(vocabulary, k=rng.randint(1, 5)) for _ in range(rng.randint(0, 8))]
        filters = [RangeFilter("price", gte=5, lt=15)] if not clauses or rng.random() < 0.3 else []
        queries.append(Query(qid, clauses, filters=filters))
    index(iter(queries), store)
    documents = [
        Document(
            rng.choices(vocabulary, k=rng.randint(0, 30)), values={"price": [rng.randint(0, 20)]}
        )
        for _ in range(80)
    ]
    expected = []
    for doc in documents:
        expected.append(
            [
                q.query_id
                for q in queries
                if all(set(group) & doc.terms for group in q.search_terms)
                and (not q.filters or any(5 <= v < 15 for v in doc.values["price"]))
            ]
        )
    assert list(QueryMatcher(store).match_many(documents)) == expected


def test_normalization():
    assert tokenize("Straße Ａ café!") == ("strasse", "a", "café")
    assert Query.from_text(1, "Data mining").search_terms == (("data",), ("mining",))
