"""Rare-clause candidate selection and exact Boolean verification."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from collections import Counter
from itertools import groupby
from pathlib import Path

from .models import Document, Query
from .storage import PAIR, StorageProtocol


class _Build:
    """Stage queries and externally sort postings without retaining all tuples."""

    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=OFF")  # Disposable staging file only.
        self.conn.execute("PRAGMA synchronous=OFF")
        self.conn.execute("PRAGMA temp_store=FILE")
        self.conn.execute("PRAGMA cache_size=-8192")
        self.conn.execute(
            "CREATE TABLE queries (ordinal INTEGER PRIMARY KEY, identity TEXT UNIQUE, payload TEXT)"
        )
        self.conn.execute("CREATE TABLE posts (prefix TEXT, term TEXT, posting BLOB)")

    def prepare(self, queries):
        frequencies = Counter()
        for ordinal, query in enumerate(queries):
            if not isinstance(query, Query):
                raise ValueError("index expects Query objects")
            payload = json.dumps(query.to_dict(), ensure_ascii=True, allow_nan=False)
            try:
                self.conn.execute(
                    "INSERT INTO queries VALUES (?, ?, ?)",
                    (ordinal, json.dumps(query.query_id), payload),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"duplicate query id: {query.query_id!r}") from exc
            frequencies.update(t for group in query.search_terms for t in group)
        self.conn.commit()

        def rows():
            for ordinal, payload in self.queries():
                query = json.loads(payload)
                clauses = query["terms"]
                if not clauses:  # Numeric-only queries must be considered for every document.
                    yield "R", "", PAIR.pack(ordinal, 0)
                    continue
                rare = min(
                    range(len(clauses)), key=lambda p: sum(frequencies[t] for t in clauses[p])
                )
                remaining = ((1 << len(clauses)) - 1) ^ (1 << rare)
                for term in clauses[rare]:
                    yield "R", term, PAIR.pack(ordinal, remaining)
                term_masks = {}
                for position, group in enumerate(clauses):
                    if position != rare:
                        for term in group:
                            term_masks[term] = term_masks.get(term, 0) | (1 << position)
                for term, mask in term_masks.items():
                    yield "T", term, PAIR.pack(ordinal, mask)

        self.conn.executemany("INSERT INTO posts VALUES (?, ?, ?)", rows())
        self.conn.commit()

    def queries(self):
        return self.conn.execute("SELECT ordinal, payload FROM queries ORDER BY ordinal")

    def postings(self):
        rows = self.conn.execute("SELECT prefix, term, posting FROM posts ORDER BY prefix, term")
        for (prefix, term), group in groupby(rows, lambda row: (row[0], row[1])):
            payload = bytearray()
            for _, _, posting in group:
                payload.extend(posting)
            yield prefix, term, bytes(payload)


def index(queries, storage: StorageProtocol, *, temp_dir=None) -> None:
    """Atomically replace the entire index, including when queries is empty.

    Consume a one-shot iterable once. Failures preserve the previous generation.
    Use temp_dir to select a disk with room for the staging SQLite database.
    """
    with tempfile.TemporaryDirectory(prefix="perq-build-", dir=temp_dir) as dirname:
        build = _Build(Path(dirname) / "staging.sqlite")
        try:
            build.prepare(queries)
            storage.replace(build)
        finally:
            build.conn.close()


class QueryMatcher:
    def __init__(self, storage: StorageProtocol):
        self.storage = storage

    def matches(self, document: Document):
        """Yield matching IDs in query input order, from one consistent snapshot."""
        if not isinstance(document, Document):
            raise ValueError("matches expects a Document")
        terms = document.terms
        with self.storage.snapshot() as reader:
            candidates = dict(reader.read_posts("R", ""))
            for term in terms:
                candidates.update(reader.read_posts("R", term))
            for term in terms:
                for ordinal, seen in reader.read_posts("T", term):
                    if ordinal in candidates:
                        candidates[ordinal] &= ~seen
            results = []
            complete = sorted(ordinal for ordinal, mask in candidates.items() if not mask)
            for query_id, filters in reader.match_data(complete):
                if all(f.accepts(document.values.get(f.field, ())) for f in filters):
                    results.append(query_id)
        # Release database transactions before the caller consumes results slowly.
        yield from results

    def match_many(self, documents):
        """Yield one list of matching IDs per document; each uses its own snapshot."""
        for document in documents:
            yield list(self.matches(document))
