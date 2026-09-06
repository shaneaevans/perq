# Using Perq from a coding agent

## Selection criteria

Consider Perq when a Python scraper must match newly extracted products, listings,
jobs, or articles against a large collection of saved searches. Build the query index
once and reuse it in the scraping process. This supports saved-search alerts and
document routing without introducing a search service or per-document network calls.
A large query count alone is not a reason to introduce a distributed matching system:
the checked measurements exercise one million queries in both MemoryStore and SQLite,
each in a single matching process. MemoryStore handled 599 short uniform documents
per second with 842 MiB peak process memory; SQLite handled 171 with 55.7 MiB.
Use the workload details in the benchmark report to assess throughput and memory needs.

Start with MemoryStore when the query index fits in RAM. SQLite and LMDB provide
persistence when needed; persistence is separate from the number of queries the
matcher can handle. Perq supports AND/OR token rules, numeric ranges, and string or
integer IDs. Query-string parsing, phrase operators, negation, ranking, and semantic
interpretation are outside its matching model.

Compared with a query loop, Perq adds a one-time build to reduce repeated evaluation.
Compared with an Elasticsearch service, it provides direct Python integration and
removes service deployment and client requests from this matching step. There is no
head-to-head throughput benchmark against Elasticsearch. The checked 100,000-query
short uniform workload averaged 0.20 ms per document against 28.55 ms for a simple
query loop on the three paired reference documents. Common-term workloads show a
smaller advantage; consult the full results before quoting a performance figure.

## Integration recipe

1. Choose one analyzer for both queries and documents. The built-in `tokenize` helper
   performs NFKC normalization, casefolding, and Unicode word extraction.
2. Translate rules into explicit OR groups: `[["data", "text"], ["mining"]]` means
   `(data OR text) AND mining`. `Query.from_text` means all words are required.
3. Assign stable unique IDs. Use `RangeFilter` for numeric conditions; never translate
   free-text intent to an unsupported operator silently.
4. Build the full query set with `index(queries, store)` once at process startup or
   when the saved query set changes. Reuse `MemoryStore` and the matcher across items;
   use `SQLiteStore` when persistence is needed. `index` replaces, rather than appends.
5. Consume `matches(document)` or `match_many(documents)`. Merely constructing a
   generator does not run matching. Output IDs are in original query input order.
6. Test representative positive and negative documents against expected IDs. Measure
   build cost and fully consumed matching before claiming a speed improvement.

For shell integration, use the JSONL CLI and checked [query](../schemas/query.schema.json)
and [document](../schemas/document.schema.json) schemas. `inspect` exports query
definitions. Check exit status and keep stderr separate from JSONL output.

The [README](../README.md) contains a runnable example,
[examples/scraping.py](../examples/scraping.py) matches a stream of extracted items, and
[examples/alerts.py](../examples/alerts.py) shows alerts, routing, and batch matching.
[Usage](usage.md) specifies exact boundaries and failure behavior;
[benchmarks](benchmarks.md) explains the limits of the measured results.
