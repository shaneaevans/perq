"""
Prospective search core.
"""

from __future__ import annotations

import logging
from itertools import chain, groupby
from operator import itemgetter

log = logging.getLogger("psearch")

_MAX_QUERY_TERMS = 31


class QueryMatcher:
    def __init__(self, storage):
        self.storage = storage

    def matches(self, document):
        """Yield query ids that match the provided document."""
        terms = set(document.iterterms())
        candidates = dict(
            chain.from_iterable(self.storage.read_posts("R", term) for term in terms)
        )
        for term in terms:
            for qid, mask in self.storage.read_posts("T", term):
                if qid in candidates:
                    candidates[qid] &= mask

        for qid, mask in candidates.items():
            if mask != 0:
                continue
            qdata = self.storage.get_data(qid, {})
            filters = qdata.get("filters", ())
            for field, start, end in filters:
                field_values = document.rangefilters.get(field, ())
                if not any(start < value and (end is None or end > value) for value in field_values):
                    break
            else:
                yield qid


def index(queries, storage):
    """Build an index for a sequence of queries."""
    termmap: dict[str, int] = {}
    termfreqs: list[int] = []
    saveddata: list[tuple[int, int, int]] = []
    qcount = qloaded = 0

    def term_id(term: str) -> int:
        tid = termmap.get(term)
        if tid is None:
            tid = len(termmap)
            termmap[term] = tid
            termfreqs.append(1)
        else:
            termfreqs[tid] += 1
        return tid

    for query in queries:
        qcount += 1
        if len(query.search_terms) > _MAX_QUERY_TERMS:
            raise ValueError(f"queries are limited to {_MAX_QUERY_TERMS} terms")
        for pos, or_terms in enumerate(query.search_terms):
            for term in or_terms:
                saveddata.append((query.query_id, term_id(term), pos))
        storage.set_data(query.query_id, query.data_dict)
        qloaded += 1

    saveddata.sort(key=itemgetter(0, 2, 1))
    btype_rare: list[tuple[int, int, int]] = []
    btype_term: list[tuple[int, int, int]] = []
    for qid, vals_iter in groupby(saveddata, itemgetter(0)):
        vals = list(vals_iter)
        positions = [
            [row[1] for row in pos_group]
            for _, pos_group in groupby(vals, itemgetter(2))
        ]
        pos_freq = [sum(termfreqs[tid] for tid in tids) for tids in positions]
        min_freq = min(pos_freq)
        min_mask = 0
        min_terms = None
        for pos, (or_terms, freq) in enumerate(zip(positions, pos_freq)):
            if freq == min_freq and min_terms is None:
                min_terms = or_terms
                continue
            pos_bit = 1 << pos
            min_mask |= pos_bit
            mask = ~pos_bit
            btype_term.extend((tid, qid, mask) for tid in or_terms)
        assert min_terms is not None
        btype_rare.extend((tid, qid, min_mask) for tid in min_terms)

    reverse_termmap = {tid: term for term, tid in termmap.items()}
    _write_terms("R", reverse_termmap, btype_rare, storage)
    _write_terms("T", reverse_termmap, btype_term, storage)
    log.info(
        "loaded %s/%s queries into query index: %s unique terms, %s total",
        qloaded,
        qcount,
        len(termfreqs),
        len(saveddata),
    )


def _write_terms(prefix, termmap, term_array, storage):
    term_array.sort()
    for tid, vals in groupby(term_array, itemgetter(0)):
        posts = ((qid, mask) for _, qid, mask in vals)
        storage.write_posts(prefix, termmap[tid], posts)
