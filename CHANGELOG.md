# Changelog

## 0.2.0 — 2026-09-06

- Rename PSearch to Perq, with the `perq` distribution, import namespace, and JSONL CLI.
- Make index replacement atomic across MemoryStore, SQLiteStore, and LMDBStore,
  remove stale postings, and preserve old generations on failure.
- Keep a consistent snapshot for each document's posting and metadata reads.
- Support string and large integer IDs, explicit inclusive/exclusive range filters,
  numeric-only rules, and 64 Boolean clauses. Reject empty clauses and duplicate IDs.
- Provide shared Unicode tokenization, immutable queries, copied JSON metadata,
  deterministic result order, and batch matching.
- Replace pickle persistence with versioned JSON and packed postings. Store one
  posting BLOB per term in SQLite; use a single write transaction in LMDB.
- Stage builds on disk and avoid retaining all posting tuples in Python memory.
- Add regression and randomized tests, cross-platform CI, installable artifact checks,
  executable examples, JSON schemas, integration documentation, and reproducible
  scale/latency/memory benchmarks with a reference matcher.
- Document single-process scraping integration and measured matching against up to
  one million saved queries. Add a streaming scraper example.
- Provide installable GitHub release artifacts and a tagged, manually dispatched
  workflow for PyPI trusted publishing.

See [migration](docs/migration.md) for intentional API and file-format changes.
