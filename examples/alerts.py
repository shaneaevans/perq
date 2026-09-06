"""Saved-search alerts, routing, and batches using the same query index."""

from perq import Document, MemoryStore, Query, QueryMatcher, RangeFilter, index


def main():
    queries = [
        Query(
            "data-alert",
            [("data", "text"), ("mining",)],
            filters=[RangeFilter("price", gte=100, lt=200)],
        ),
        Query.from_text("python-route", "python", metadata={"destination": "engineering"}),
    ]
    with MemoryStore() as store:
        index(queries, store)
        matcher = QueryMatcher(store)
        assert list(
            matcher.matches(Document.from_text("Data mining", values={"price": [150]}))
        ) == ["data-alert"]
        destinations = {q.query_id: q.metadata.get("destination") for q in store.queries()}
        assert [
            destinations[qid] for qid in matcher.matches(Document.from_text("Python release"))
        ] == ["engineering"]
        batch = list(
            matcher.match_many([Document.from_text("Python"), Document.from_text("Unrelated")])
        )
        assert batch == [["python-route"], []]
        print(batch)


if __name__ == "__main__":
    main()
