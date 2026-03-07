"""
Helpers for recreating queries from an index.
"""

from __future__ import annotations

from collections import defaultdict


def first_zero(bits):
    index = 0
    while bits & 1:
        bits >>= 1
        index += 1
    return index


def recreate_queries(storage):
    queries = defaultdict(list)
    for ptype, key, values in storage.iteritems():
        for query_id, mask in values:
            position = first_zero(mask)
            query = queries[query_id]
            if len(query) <= position:
                query.extend([] for _ in range(position - len(query) + 1))
            query[position].append(key)
    for key in sorted(queries):
        query = queries[key]
        for or_terms in query:
            or_terms.sort()
        yield key, query
