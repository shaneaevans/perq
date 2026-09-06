import pytest

from perq import Document, Query, RangeFilter


@pytest.mark.parametrize(
    "clauses", [[[]], [["alpha"], []], ["alpha"], [[""]], [[1]], "alpha", [("a",)] * 65]
)
def test_invalid_clauses_rejected(clauses):
    with pytest.raises(ValueError):
        Query(1, clauses)


@pytest.mark.parametrize("identity", [None, True, 1.2, "", []])
def test_invalid_ids_rejected(identity):
    with pytest.raises(ValueError):
        Query.from_text(identity, "alpha")


@pytest.mark.parametrize(
    "bounds",
    [
        {},
        {"gt": 1, "gte": 2},
        {"lt": 1, "lte": 2},
        {"gt": 3, "lt": 2},
        {"gt": 2, "lte": 2},
        {"gt": float("nan")},
        {"gte": True},
    ],
)
def test_invalid_ranges_rejected(bounds):
    with pytest.raises(ValueError):
        RangeFilter("price", **bounds)


def test_inclusive_equal_range_and_open_bounds():
    assert RangeFilter("n", gte=2, lte=2).accepts([2])
    assert RangeFilter("n", lt=0).accepts([-1])
    assert not RangeFilter("n", gt=0).accepts([0])


@pytest.mark.parametrize("metadata", [{"x": float("nan")}, {"x": object()}, {1: "value"}, []])
def test_invalid_metadata_rejected(metadata):
    with pytest.raises(ValueError):
        Query.from_text(1, "a", metadata=metadata)


def test_query_defensively_copies_terms_and_metadata():
    terms = [["a"]]
    metadata = {"x": [1]}
    query = Query(1, terms, metadata=metadata)
    terms[0].append("b")
    metadata["x"].append(2)
    query.metadata["x"].append(3)
    assert query.search_terms == (("a",),)
    assert query.metadata == {"x": [1]}
    assert Query.from_dict(query.to_dict()) == query


@pytest.mark.parametrize(
    "value",
    [
        {"terms": ["a"], "text": "a"},
        {},
        {"text": "a", "typo": 1},
        {"text": "a", "values": {"n": [float("inf")]}},
        {"text": "a", "values": {"n": 1}},
    ],
)
def test_invalid_document_json_rejected(value):
    with pytest.raises(ValueError):
        Document.from_dict(value)


def test_empty_query_rejected():
    with pytest.raises(ValueError):
        Query(1)


@pytest.mark.parametrize(
    "value",
    [
        {"id": 1, "terms": {"a": ["b"]}},
        {"id": 1, "terms": [["a"]], "metadata": None},
        {"id": 1, "terms": [["a"]], "filters": {}},
        {"id": 1, "filters": [{"field": "n", "gt": None, "lt": 10}]},
        {"id": 1, "filters": [{"field": "n", "gte": 1, "typo": 2}]},
    ],
)
def test_invalid_query_json_structure(value):
    with pytest.raises(ValueError):
        Query.from_dict(value)


@pytest.mark.parametrize("value", [{"terms": {"alpha": True}}, {"terms": [], "values": None}])
def test_invalid_document_json_structure(value):
    with pytest.raises(ValueError):
        Document.from_dict(value)
