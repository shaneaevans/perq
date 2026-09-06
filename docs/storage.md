# Storage choices for 2026

Perq performs indexed point lookups on term postings and query metadata. Its
supported storage options are memory, SQLite, and optional LMDB. This keeps its
deployment model embedded in a Python process, with no database service to operate.

## SQLite: default persistence

SQLite remains a good fit for an application index file: it is portable, transactional,
and included with Python. [SQLite's application-file guidance](https://www.sqlite.org/appfileformat.html)
describes these properties. The backend uses WAL and full synchronous durability,
one BLOB per term posting list, and a transaction covering the complete replacement.
Each matching operation pins a read snapshot across both postings and query metadata.

Use a separate `SQLiteStore` connection per thread and for overlapping operations.
Multiple processes can read a local index while a writer replaces it. SQLite serializes
writers; the default connection timeout is five seconds. Use a local filesystem:
[WAL requires processes to share memory on the same host](https://www.sqlite.org/wal.html).
Close writers before copying an index; a live WAL index may require its `-wal` and
`-shm` companions. Retained old read snapshots can delay WAL cleanup.

## LMDB: optional read-heavy storage

LMDB supplies a persistent memory-mapped key-value index and cheap snapshot reads.
[Its documentation](https://lmdb.readthedocs.io/en/latest/index.html) describes
concurrent readers, a single writer, and same-host multi-process access. The backend
keeps locking enabled for readers and performs one transaction per replacement,
including deletion of obsolete entries. All lookups for a document share one read
transaction. This replaces the old per-key transaction approach.

Install the `lmdb` extra. Open only one environment for a given path in each process;
reuse its `LMDBStore` and create matchers from it. Separate processes may open the
same path. Do not inherit an open environment across a fork; reopen it in the child.
Do not close a store while another operation is using it. Reader lock-file permissions
are required even for a read-only store. Use a local filesystem.

The default map reservation is 1 GiB. Set `map_size=8 << 30`, for example, to reserve
8 GiB of virtual address space for a larger index; this does not allocate 8 GiB of RAM.
Leave room for an old generation plus a new build and readers retaining old pages.
`MapFullError` aborts the new build and preserves the old one. Close all local handles
before reopening with a larger reservation. Coordinate resizing with other processes
as described in the LMDB documentation; this library does not silently resize a live
multi-process environment.

Posting keys use a fixed-size digest to accommodate long tokens. The original token
is stored alongside the posting list and checked on lookup; a build detecting a
digest collision fails instead of merging unrelated terms.

## MemoryStore

The memory backend stores compact packed postings and immutable query definitions.
A completed build swaps one state reference; readers already using the old snapshot
continue to see it. The old and new indexes can coexist during replacement, so size
RAM for that overlap. There is no custom file serializer: persist with SQLite or LMDB.

## Why no other built-in databases?

| Option | Assessment for this library |
|---|---|
| GDBM / Tokyo Cabinet | Removed by the Python 3 modernization; maintaining additional legacy adapters adds little value here. |
| DuckDB | Optimized for analytical scans and bulk operations. That is a different access pattern from per-document posting lookups. It remains useful for analyzing exported benchmark or match results. |
| PostgreSQL / Redis | Useful when an application requires a shared network service. A network round trip for each posting lookup would require a different batched/service architecture to be competitive. |
| RocksDB | Potentially useful for a future write-heavy incremental engine. The present workload uses snapshot rebuilds and repeated reads, so an additional native dependency and backend are not justified yet. |

DuckDB's [workload guidance](https://duckdb.org/docs/stable/guides/performance/how_to_tune_workloads)
and [transaction design](https://duckdb.org/2024/10/30/analytics-optimized-concurrent-transactions)
explain its analytical focus. These are architectural choices, not claims that a
particular backend wins every benchmark. Measure your workload using
[the benchmark runner](benchmarks.md) before choosing SQLite or LMDB for performance.
