# Usage and matching semantics

## Inside a scraper

Build the saved-query index once and reuse a `QueryMatcher` for each extracted item.
Start with `MemoryStore` when the index fits in RAM. Pass the fields you want to
search, such as a product title and description, to `Document.from_text`, and pass
extracted numbers such as price through `values`. Use the returned query IDs to
identify the saved searches or subscriptions that matched.

The [streaming example](../examples/scraping.py) accepts an iterator of extracted
items, applies keyword and price rules, and emits matching search IDs. It builds
outside the item loop and keeps matching in the scraper's Python process.

## Terms and normalization

`Query(id, search_terms, filters=(), metadata=None)` takes a sequence of OR groups;
all groups must match. `[("data", "text"), ("mining",)]` is `(data OR text) AND mining`.
Terms are non-empty, case-sensitive strings. Repeated terms inside a group are
deduplicated; the same document term can satisfy more than one group. Group order
does not affect matching. Maximum: 64 groups, with no fixed limit on OR alternatives.

`tokenize(text)`, `Query.from_text(id, text)`, and `Document.from_text(text)` share
Unicode NFKC normalization, casefolding, and Python's `\w+` token extraction. This
keeps Unicode word characters, digits, and underscores, and splits at punctuation.
It does not stem, strip accents, remove stop words, or expand synonyms.
`Query.from_text` requires **every word**; the words `AND`, `OR`, and `NOT` have no
special syntax. Empty normalized text requires numeric filters to form a valid query.

Supply your own normalized terms to `Query` and `Document` to use a different
analyzer. Apply the same analyzer to both. For field matching, explicitly namespace
terms on both sides, for example `title:python` and `body:python`. Plain `python`
does not match either namespaced term. The document API does not imply field scope.

## Numeric filters

Use `RangeFilter("price", gte=100, lt=200)` for `[100, 200)`.
`gt` and `lt` exclude their bounds; `gte` and `lte` include them. A bound can be
omitted. At least one bound is required. Reversed or empty ranges, ambiguous pairs
such as both `gt` and `gte`, booleans, infinity, and NaN are rejected.

`Document(terms, values={"price": [100, 150]})` supports multi-valued numeric fields.
Each filter requires at least one value in its range; all filters must pass.
Separate filters on the same field can be satisfied by different values. Put the
lower and upper bounds in **one RangeFilter** when the same value must satisfy both.
Missing and empty numeric fields fail that field's filter.

`Query("price-alert", filters=[RangeFilter("price", lt=50)])` has no text clauses
and is considered for every document. Its cost scales with the number of such rules.
An entirely empty query is rejected.

## IDs, metadata, and results

IDs are non-empty strings or integers; booleans and floats are rejected. Integer
`1` and string `"1"` are distinct. Large external IDs are stored as JSON, separately
from compact internal posting ordinals. Duplicate IDs in a build fail the whole build.

Metadata is a JSON object with string keys and finite numbers. It is copied at query
construction and on access, and does not participate in matching. Query objects are
immutable. `store.queries()` yields the original definitions in input order. Use
their metadata to map matching IDs to alert subscriptions or routing destinations.

`QueryMatcher(store).matches(document)` yields IDs in query input order. It computes
the complete result against a single snapshot and closes that read transaction
before yielding. Result memory is proportional to candidate and matching query counts.
`match_many(documents)` yields one list per document and takes a **new snapshot for
each document**; a concurrent replacement can become visible between documents.

## Index lifecycle

`index(queries, store, temp_dir=None)` accepts a one-shot iterable. It stages and
validates the query set, builds postings, then replaces the entire stored generation.
This is a rebuild, not append or upsert. An empty iterable clears the index.
Input errors, duplicate IDs, interrupted iterators, and failed storage writes preserve
the previous generation. Initializing a new disk store can create an empty, valid
index even if its first build fails.

Use context managers to close disk stores. `MemoryStore` has no file persistence;
choose SQLite or LMDB when the index must survive process exit. Persistent indexes
are versioned and contain JSON metadata and packed integer postings. Legacy pickle
indexes are not loaded. Retain your original query definitions as the source of truth.

See [storage](storage.md) for concurrency, LMDB map sizing, and filesystem constraints.

## JSONL CLI

`perq build --index PATH --queries FILE` replaces a SQLite index.
Add `--backend lmdb` to **every command** when using LMDB. For large LMDB indexes,
pass `--map-size BYTES` when building and reopening. `--temp-dir DIR` chooses build
staging storage. Query input is one JSON object per line, using `id`, `terms`,
`filters`, and `metadata` as shown in `schemas/query.schema.json`.

`perq match --index PATH --documents FILE` accepts exactly one of
`text` or `terms`, optional numeric `values`, and an optional document `id`.
An omitted document ID becomes its zero-based record position, ignoring blank lines.
One output record contains `id` and `matches`. `inspect` exports query JSONL that can
be passed back into `build`.

Input defaults to `-` (stdin). Blank lines are ignored. Output is UTF-8 JSONL on stdout;
build summaries and errors go to stderr. Exit status is 0 on success, 2 on invalid
input or an operational error. Errors identify the input line where applicable.
Matching streams output: if a later document is invalid, earlier output may already
have been emitted. Check the exit status before treating a batch as complete.

The JSON schemas validate structure; runtime validation also checks range ordering,
finite numbers, and duplicate query IDs across records.
