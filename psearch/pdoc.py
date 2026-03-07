"""
Document model.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import chain


class Document:
    """Prospective search document."""

    def __init__(self, textsearchterms, rangefilters=None):
        self.textsearchterms = textsearchterms
        self.rangefilters = rangefilters or {}
        self._statscache = {}

    def iterterms(self):
        return chain.from_iterable(
            chain.from_iterable(self.textsearchterms.values())
        )

    def _stats(self, field):
        stats = self._statscache.get(field)
        if stats is not None:
            return stats
        tfs = defaultdict(int)
        doclen = 0
        for fieldentry in self.textsearchterms.get(field, ()):
            doclen += len(fieldentry)
            for term in fieldentry:
                tfs[term] += 1
        stats = (tfs, doclen)
        self._statscache[field] = stats
        return stats

    def termfreq_and_length(self, *fields):
        tfs, doclen = self._stats(fields[0])
        merged = dict(tfs)
        for field in fields[1:]:
            field_tfs, field_doclen = self._stats(field)
            doclen += field_doclen
            for term, freq in field_tfs.items():
                merged[term] = freq + merged.get(term, 0)
        return merged, doclen

    def totuple(self):
        return self.textsearchterms, self.rangefilters

    @classmethod
    def fromtuple(cls, data):
        return cls(*data)

    def __str__(self):
        args = [f"textsearchterms={self.textsearchterms!r}"]
        if self.rangefilters:
            args.append(f"rangefilters={self.rangefilters!r}")
        return f"Document({','.join(args)})"

    __repr__ = __str__
