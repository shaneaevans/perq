"""Atomic index snapshots in memory, SQLite, or optional LMDB."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from .models import Query, RangeFilter

FORMAT_VERSION = b"perq:1"
PAIR = struct.Struct("<QQ")  # internal query ordinal and 64 clause bits


class IndexFormatError(ValueError):
    """The index is incompatible; rebuild it from its original queries."""


def _check_format(value):
    if value != FORMAT_VERSION:
        raise IndexFormatError("unsupported index format; rebuild from the original queries")


def _query(payload) -> Query:
    return Query.from_dict(json.loads(payload))


def _match_payload(payload):
    query = json.loads(payload)
    return json.dumps([query["id"], query["filters"]], separators=(",", ":"))


def _match_data(payload):
    query_id, filters = json.loads(payload)
    return query_id, tuple(RangeFilter(**f) for f in filters)


class Snapshot(Protocol):
    def read_posts(self, prefix: str, term: str): ...
    def match_data(self, ordinals): ...
    def queries(self): ...


class StorageProtocol(Protocol):
    def snapshot(self): ...
    def replace(self, build): ...
    def close(self): ...


class _Store:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def queries(self):
        """Yield stored queries in their original input order."""
        with self.snapshot() as reader:
            yield from reader.queries()


class _MemorySnapshot:
    def __init__(self, posts, queries):
        self.posts = posts
        self.data = queries

    def read_posts(self, prefix, term):
        return PAIR.iter_unpack(self.posts.get((prefix, term), b""))

    def match_data(self, ordinals):
        for ordinal in ordinals:
            query = self.data[ordinal]
            yield query.query_id, query.filters

    def queries(self):
        return iter(self.data)


class MemoryStore(_Store):
    """Compact in-memory index. Use SQLiteStore or LMDBStore for persistence."""

    def __init__(self):
        self._state = _MemorySnapshot({}, ())

    @contextmanager
    def snapshot(self):
        yield self._state

    def replace(self, build):
        data = tuple(_query(payload) for _, payload in build.queries())
        posts = {(prefix, term): payload for prefix, term, payload in build.postings()}
        self._state = _MemorySnapshot(posts, data)

    def close(self):
        pass


class _SQLiteSnapshot:
    def __init__(self, conn):
        self.conn = conn

    def read_posts(self, prefix, term):
        row = self.conn.execute(
            "SELECT payload FROM posts WHERE prefix=? AND term=?", (prefix, term)
        ).fetchone()
        return PAIR.iter_unpack(row[0] if row else b"")

    def match_data(self, ordinals):
        for start in range(0, len(ordinals), 400):
            chunk = ordinals[start : start + 400]
            placeholders = ",".join("?" for _ in chunk)
            rows = self.conn.execute(
                f"SELECT matchdata FROM queries WHERE ordinal IN ({placeholders}) ORDER BY ordinal",
                chunk,
            )
            for row in rows:
                yield _match_data(row[0])

    def queries(self):
        return (
            _query(row[0])
            for row in self.conn.execute("SELECT payload FROM queries ORDER BY ordinal")
        )


class SQLiteStore(_Store):
    """Default persistent backend; one connection per thread, WAL snapshots."""

    def __init__(self, fname: str | Path, readmode: bool = False):
        self.readmode = readmode
        self._active = False
        uri = Path(fname).resolve().as_uri()
        self.conn = sqlite3.connect(
            f"{uri}?mode={'ro' if readmode else 'rwc'}", uri=True, isolation_level=None
        )
        try:
            tables = {
                r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if tables:
                if "metadata" not in tables:
                    raise IndexFormatError("legacy or unrelated SQLite file; use a new index path")
                row = self.conn.execute("SELECT value FROM metadata WHERE key='format'").fetchone()
                _check_format(row[0] if row else None)
            elif readmode:
                raise IndexFormatError("file is not a Perq index")
            if not readmode:
                self.conn.execute("PRAGMA journal_mode=WAL")
                self.conn.execute("PRAGMA synchronous=FULL")
                self.conn.execute("BEGIN IMMEDIATE")
                try:
                    self.conn.execute(
                        "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value BLOB NOT NULL)"
                    )
                    self.conn.execute(
                        "CREATE TABLE IF NOT EXISTS queries (ordinal INTEGER PRIMARY KEY, payload TEXT NOT NULL, matchdata TEXT NOT NULL)"
                    )
                    self.conn.execute(
                        "CREATE TABLE IF NOT EXISTS posts (prefix TEXT, term TEXT, payload BLOB NOT NULL, PRIMARY KEY(prefix, term)) WITHOUT ROWID"
                    )
                    self.conn.execute(
                        "INSERT OR IGNORE INTO metadata VALUES ('format', ?)", (FORMAT_VERSION,)
                    )
                    self.conn.commit()
                except BaseException:
                    self.conn.rollback()
                    raise
        except BaseException:
            self.conn.close()
            raise

    @contextmanager
    def snapshot(self):
        if self._active:
            raise RuntimeError("use a separate store connection for overlapping operations")
        self._active = True
        try:
            self.conn.execute("BEGIN")
            # Pin a WAL generation before any posting or metadata reads.
            self.conn.execute("SELECT value FROM metadata WHERE key='format'").fetchone()
            yield _SQLiteSnapshot(self.conn)
        finally:
            self.conn.rollback()
            self._active = False

    def replace(self, build):
        if self.readmode:
            raise PermissionError("index was opened read-only")
        if self._active:
            raise RuntimeError("cannot replace an index inside an active snapshot")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute("DELETE FROM queries")
            self.conn.execute("DELETE FROM posts")
            self.conn.executemany(
                "INSERT INTO queries VALUES (?, ?, ?)",
                (
                    (ordinal, payload, _match_payload(payload))
                    for ordinal, payload in build.queries()
                ),
            )
            self.conn.executemany("INSERT INTO posts VALUES (?, ?, ?)", build.postings())
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def close(self):
        self.conn.close()


def _post_key(prefix, term):
    # Fixed-length keys also support tokens longer than LMDB's key-size limit.
    return prefix.encode("ascii") + hashlib.sha256(term.encode("utf-8")).digest()


class _LMDBSnapshot:
    def __init__(self, txn):
        self.txn = txn

    def read_posts(self, prefix, term):
        payload = self.txn.get(_post_key(prefix, term))
        if payload is None:
            return iter(())
        size = struct.unpack_from("<I", payload)[0]
        if payload[4 : 4 + size] != term.encode("utf-8"):
            return iter(())
        return PAIR.iter_unpack(payload[4 + size :])

    def match_data(self, ordinals):
        for ordinal in ordinals:
            yield _match_data(self.txn.get(b"M" + struct.pack(">Q", ordinal)))

    def queries(self):
        with self.txn.cursor() as cursor:
            if cursor.set_range(b"Q"):
                for key, payload in cursor:
                    if not key.startswith(b"Q"):
                        break
                    yield _query(payload)


class LMDBStore(_Store):
    """Optional read-heavy backend; one open environment per path per process."""

    def __init__(self, fname: str | Path, readmode: bool = False, map_size: int = 1 << 30):
        try:
            import lmdb
        except ImportError as exc:
            raise RuntimeError("install perq[lmdb] to use LMDBStore") from exc
        self.readmode = readmode
        self.env = lmdb.open(
            str(fname),
            subdir=False,
            readonly=readmode,
            create=not readmode,
            lock=True,
            map_size=map_size,
        )
        try:
            with self.env.begin(write=not readmode) as txn:
                version = txn.get(b"!format")
                if version is None and not readmode and txn.stat()["entries"] == 0:
                    txn.put(b"!format", FORMAT_VERSION)
                else:
                    _check_format(version)
        except BaseException:
            self.env.close()
            raise

    @contextmanager
    def snapshot(self):
        with self.env.begin() as txn:
            yield _LMDBSnapshot(txn)

    def replace(self, build):
        if self.readmode:
            raise PermissionError("index was opened read-only")
        with self.env.begin(write=True) as txn:
            with txn.cursor() as cursor:
                while cursor.first():
                    cursor.delete()
            txn.put(b"!format", FORMAT_VERSION)
            for ordinal, payload in build.queries():
                txn.put(b"Q" + struct.pack(">Q", ordinal), payload.encode("utf-8"))
                txn.put(b"M" + struct.pack(">Q", ordinal), _match_payload(payload).encode("utf-8"))
            for prefix, term, payload in build.postings():
                key = _post_key(prefix, term)
                term_bytes = term.encode("utf-8")
                existing = txn.get(key)
                if existing is not None:
                    size = struct.unpack_from("<I", existing)[0]
                    if existing[4 : 4 + size] != term_bytes:
                        raise ValueError("term hash collision; use the SQLite backend")
                txn.put(key, struct.pack("<I", len(term_bytes)) + term_bytes + payload)

    def close(self):
        self.env.close()
