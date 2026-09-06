"""Match extracted scraper items against a reusable in-process query index."""

import json

from perq import Document, MemoryStore, Query, QueryMatcher, RangeFilter, index


def match_items(items, matcher):
    """Consume an iterable of extracted items and emit their matching search IDs."""
    for item in items:
        text = " ".join((item["title"], item.get("description", "")))
        values = {"price_eur": [item["price_eur"]]} if item.get("price_eur") is not None else {}
        document = Document.from_text(text, values=values)
        query_ids = list(matcher.matches(document))
        if query_ids:
            yield {"url": item["url"], "query_ids": query_ids}


def main():
    # These could be saved searches loaded from your application's database.
    queries = [
        Query(
            "camera-alert",
            [("sony",), ("a7", "a7iii")],
            filters=[RangeFilter("price_eur", lte=1200)],
        ),
        Query.from_text("lens-alert", "canon lens"),
    ]
    # An example stream of items already extracted and normalized by a scraper.
    # Real callers can pass their item iterator without collecting it into a list.
    items = [
        {
            "url": "https://example.com/listings/1",
            "title": "Sony A7 III mirrorless camera",
            "description": "Used body",
            "price_eur": 950,
        },
        {"url": "https://example.com/listings/2", "title": "Sony A7 III camera", "price_eur": 1500},
        {"url": "https://example.com/listings/3", "title": "Canon RF lens", "price_eur": 350},
    ]
    with MemoryStore() as store:
        index(queries, store)  # Build once, outside the per-item loop.
        matcher = QueryMatcher(store)
        for result in match_items(iter(items), matcher):
            print(json.dumps(result))


if __name__ == "__main__":
    main()
