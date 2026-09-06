# Migrating from the unreleased 0.1 API

Version 0.2 deliberately simplifies the API and breaks compatibility with the legacy
project. The repository has little established use, so it does not maintain aliases
that would recreate the unrelated `psearch` package's import collision.

- The distribution is `perq`; imports use `perq`.
- `Document` takes a flat sequence of normalized terms and optional `values`.
  Replace nested `textsearchterms` with flattened terms, or use `Document.from_text`.
  Replace `rangefilters` with `values`.
- Replace filter triples `(field, start, end)` with
  `RangeFilter(field, gt=start, lt=end)`. Use `gte` / `lte` when bounds are inclusive.
  Optional bounds are omitted or set to `None`.
- Pass user data in `metadata={...}`. Metadata must be JSON-serializable; arbitrary
  Python objects and pickle payloads are no longer supported.
- `index` replaces the whole query collection and rejects duplicate IDs. It does
  not append or incrementally update. Empty input clears the index.
- The clause limit is 64, previously 31. Empty OR clauses fail explicitly.
  Numeric-only queries now work; an entirely empty query is rejected.
- External IDs may be strings or integers, including integers larger than 32 bits.
  Matching order is the input order of the stored queries.
- `MemoryStore` no longer accepts a filename or uses pickle. Use SQLite or LMDB
  for persistence. Old database and pickle files must be rebuilt from original queries
  into a new path. The new backends reject incompatible index formats.
- Low-level posting mutation methods are replaced by atomic index replacement and
  consistent snapshots. Custom backend implementations should follow `StorageProtocol`.
  `store.queries()` returns the original definitions, replacing query reconstruction.
