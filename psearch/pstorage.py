"""
Storage backends for prospective search indexes.
"""

from __future__ import annotations

import pickle
import sqlite3
import struct
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, Protocol, TypeAlias

Posting: TypeAlias = tuple[int, int]
QueryData: TypeAlias = dict[str, Any]

_POSTING_STRUCT = struct.Struct("<ii")
_TERM_KEY_HEADER = struct.Struct(">II")


class StorageProtocol(Protocol):
    def write_posts(self, prefix: str, term: str, values: Iterable[Posting]) -> None: ...

    def read_posts(self, prefix: str, term: str) -> Iterator[Posting]: ...

    def set_data(self, qid: int, data: QueryData) -> None: ...

    def get_data(self, qid: int, default: Any = None) -> Any: ...

    def iteritems(self) -> Iterator[tuple[str, str, Iterator[Posting]]]: ...

    def begin_bulk_load(self) -> None: ...

    def end_bulk_load(self) -> None: ...

    def abort_bulk_load(self) -> None: ...


class MemoryStore:
    """In-memory storage with optional pickle persistence."""

    def __init__(self, fname: str | None = None, readmode: bool = False):
        self.fname = fname
        self.readmode = readmode
        if readmode and fname is not None:
            with open(fname, "rb") as pfile:
                self.postmap = pickle.load(pfile)
                self.data = pickle.load(pfile)
        else:
            self.postmap: dict[tuple[str, str], list[Posting]] = {}
            self.data: dict[int, QueryData] = {}

    def close(self) -> None:
        if self.fname is None or self.readmode:
            return
        with open(self.fname, "wb") as pfile:
            pickle.dump(self.postmap, pfile, protocol=pickle.HIGHEST_PROTOCOL)
            pickle.dump(self.data, pfile, protocol=pickle.HIGHEST_PROTOCOL)

    def write_posts(
        self, prefix: str, term: str, values: Iterable[Posting]
    ) -> None:
        self.postmap[(prefix, term)] = list(values)

    def read_posts(self, prefix: str, term: str) -> Iterator[Posting]:
        return iter(self.postmap.get((prefix, term), ()))

    def set_data(self, qid: int, data: QueryData) -> None:
        self.data[qid] = data

    def get_data(self, qid: int, default: Any = None) -> Any:
        return self.data.get(qid, default)

    def iteritems(self) -> Iterator[tuple[str, str, Iterator[Posting]]]:
        for (prefix, term), values in self.postmap.items():
            yield prefix, term, iter(values)

    def begin_bulk_load(self) -> None:
        return None

    def end_bulk_load(self) -> None:
        return None

    def abort_bulk_load(self) -> None:
        return None


class SQLiteStore:
    """SQLite-backed storage suitable for durable embedded indexes."""

    def __init__(self, fname: str, readmode: bool = False):
        self.fname = fname
        self.readmode = readmode
        self._in_bulk_load = False
        uri = Path(fname).resolve().as_uri()
        if readmode:
            self.conn = sqlite3.connect(f"{uri}?mode=ro", uri=True)
        else:
            self.conn = sqlite3.connect(fname)
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        if self.readmode:
            return
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS posts (
                prefix TEXT NOT NULL,
                term TEXT NOT NULL,
                qid INTEGER NOT NULL,
                mask INTEGER NOT NULL,
                PRIMARY KEY(prefix, term, qid, mask)
            );
            CREATE INDEX IF NOT EXISTS idx_posts_prefix_term
                ON posts(prefix, term, qid);
            CREATE TABLE IF NOT EXISTS qdata (
                qid INTEGER PRIMARY KEY,
                payload BLOB NOT NULL
            );
            """
        )
        self.conn.commit()

    def close(self) -> None:
        if self._in_bulk_load:
            self.end_bulk_load()
        self.conn.close()

    def write_posts(
        self, prefix: str, term: str, values: Iterable[Posting]
    ) -> None:
        rows = [(prefix, term, qid, mask) for qid, mask in values]
        if not rows:
            return
        self.conn.executemany(
            "INSERT OR REPLACE INTO posts(prefix, term, qid, mask) VALUES (?, ?, ?, ?)",
            rows,
        )
        if not self._in_bulk_load:
            self.conn.commit()

    def read_posts(self, prefix: str, term: str) -> Iterator[Posting]:
        rows = self.conn.execute(
            "SELECT qid, mask FROM posts WHERE prefix = ? AND term = ? ORDER BY qid",
            (prefix, term),
        )
        return ((int(row["qid"]), int(row["mask"])) for row in rows)

    def set_data(self, qid: int, data: QueryData) -> None:
        payload = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
        self.conn.execute(
            "INSERT OR REPLACE INTO qdata(qid, payload) VALUES (?, ?)", (qid, payload)
        )
        if not self._in_bulk_load:
            self.conn.commit()

    def get_data(self, qid: int, default: Any = None) -> Any:
        row = self.conn.execute(
            "SELECT payload FROM qdata WHERE qid = ?", (qid,)
        ).fetchone()
        if row is None:
            return default
        return pickle.loads(row["payload"])

    def iteritems(self) -> Iterator[tuple[str, str, Iterator[Posting]]]:
        rows = self.conn.execute(
            "SELECT prefix, term, qid, mask FROM posts ORDER BY prefix, term, qid"
        )
        current_key: tuple[str, str] | None = None
        postings: list[Posting] = []
        for row in rows:
            key = (str(row["prefix"]), str(row["term"]))
            posting = (int(row["qid"]), int(row["mask"]))
            if current_key is None:
                current_key = key
            if key != current_key:
                assert current_key is not None
                yield current_key[0], current_key[1], iter(postings)
                current_key = key
                postings = []
            postings.append(posting)
        if current_key is not None:
            yield current_key[0], current_key[1], iter(postings)

    def begin_bulk_load(self) -> None:
        if self.readmode or self._in_bulk_load:
            return
        self.conn.execute("BEGIN IMMEDIATE")
        self._in_bulk_load = True

    def end_bulk_load(self) -> None:
        if self.readmode or not self._in_bulk_load:
            return
        self.conn.commit()
        self._in_bulk_load = False

    def abort_bulk_load(self) -> None:
        if self.readmode or not self._in_bulk_load:
            return
        self.conn.rollback()
        self._in_bulk_load = False


class LMDBStore:
    """LMDB-backed storage for high-throughput local indexes."""

    def __init__(self, fname: str, readmode: bool = False, map_size: int = 1 << 30):
        try:
            import lmdb
        except ImportError as exc:
            raise RuntimeError("LMDBStore requires the 'lmdb' package") from exc

        self._lmdb = lmdb
        self.fname = fname
        self.readmode = readmode
        self.env = lmdb.open(
            fname,
            subdir=False,
            readonly=readmode,
            create=not readmode,
            lock=not readmode,
            map_size=map_size,
            max_dbs=1,
        )

    def close(self) -> None:
        self.env.close()

    def _posts_key(self, prefix: str, term: str) -> bytes:
        prefix_bytes = prefix.encode("utf-8")
        term_bytes = term.encode("utf-8")
        return b"P" + _TERM_KEY_HEADER.pack(len(prefix_bytes), len(term_bytes)) + prefix_bytes + term_bytes

    def _data_key(self, qid: int) -> bytes:
        return f"D{qid}".encode("ascii")

    def _decode_posts_key(self, payload: bytes) -> tuple[str, str]:
        prefix_len, term_len = _TERM_KEY_HEADER.unpack_from(payload, 1)
        offset = 1 + _TERM_KEY_HEADER.size
        prefix = payload[offset : offset + prefix_len].decode("utf-8")
        offset += prefix_len
        term = payload[offset : offset + term_len].decode("utf-8")
        return prefix, term

    def _encode_posts(self, values: Iterable[Posting]) -> bytes:
        return b"".join(_POSTING_STRUCT.pack(qid, mask) for qid, mask in values)

    def _decode_posts(self, payload: bytes) -> Iterator[Posting]:
        for offset in range(0, len(payload), _POSTING_STRUCT.size):
            yield _POSTING_STRUCT.unpack_from(payload, offset)

    def write_posts(
        self, prefix: str, term: str, values: Iterable[Posting]
    ) -> None:
        payload = self._encode_posts(values)
        with self.env.begin(write=True) as txn:
            txn.put(self._posts_key(prefix, term), payload)

    def read_posts(self, prefix: str, term: str) -> Iterator[Posting]:
        with self.env.begin() as txn:
            payload = txn.get(self._posts_key(prefix, term))
        if payload is None:
            return iter(())
        return self._decode_posts(payload)

    def set_data(self, qid: int, data: QueryData) -> None:
        payload = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
        with self.env.begin(write=True) as txn:
            txn.put(self._data_key(qid), payload)

    def get_data(self, qid: int, default: Any = None) -> Any:
        with self.env.begin() as txn:
            payload = txn.get(self._data_key(qid))
        if payload is None:
            return default
        return pickle.loads(payload)

    def iteritems(self) -> Iterator[tuple[str, str, Iterator[Posting]]]:
        with self.env.begin() as txn:
            with txn.cursor() as cursor:
                for key, payload in cursor:
                    if not key.startswith(b"P"):
                        continue
                    prefix, term = self._decode_posts_key(key)
                    postings = list(self._decode_posts(payload))
                    yield prefix, term, iter(postings)

    def begin_bulk_load(self) -> None:
        return None

    def end_bulk_load(self) -> None:
        return None

    def abort_bulk_load(self) -> None:
        return None
