# Matching documents against a million saved queries in one Python process

Perq indexes the queries once and uses each document's terms to select candidates.
The checked single-process runs handled **100,000 saved queries at 5,801 documents
per second**, and **one million at 599 documents per second**, using MemoryStore
with short uniform documents. Query count alone does not require a matching service.

This fits a scraper that repeatedly matches extracted products, listings, jobs, or
articles against saved searches: build once, then reuse the matcher as items arrive.
The [scraping example](../examples/scraping.py) shows this integration. The timings
below measure matching synthetic, pre-tokenized documents; fetching, HTML extraction,
tokenization, and alert delivery are additional application costs.

## Compared with looping over every query

For **100,000 queries in MemoryStore**, the indexed matcher and an independent Python
query loop produced identical results on the three paired documents in each case:

| Document workload | Perq mean per document | Query loop mean per document | Matching speedup |
|---|---:|---:|---:|
| 30 tokens, uniform vocabulary | 0.20 ms | 28.55 ms | 142× |
| 300 tokens, uniform vocabulary | 1.62 ms | 30.26 ms | 18.6× |
| 30 tokens, common terms (Zipf) | 11.75 ms | 34.27 ms | 2.9× |
| 300 tokens, common terms (Zipf) | 26.25 ms | 41.51 ms | 1.6× |

These are matching-only ratios calculated from unrounded paired means. Indexing
the short uniform case took 3.29 seconds, including query generation. Reusing an index
across many items amortizes this cost; a simple loop can be sufficient for a small
query set or a one-off batch. Common terms and long documents increase candidate
and output counts, reducing the benefit of candidate selection.

## Single-process capacity and storage tradeoffs

Each case uses one matching thread in one process, with 100 short, 30-token uniform
documents. Build time includes query generation. Peak RSS covers both build and match:

| Saved queries | Backend | Documents/s | p95 per document | Build time | Peak process RSS |
|---|---|---:|---:|---:|---:|
| 100,000 | MemoryStore | 5,801 | 0.22 ms | 3.29 s | 132 MiB |
| 1,000,000 | MemoryStore | 599 | 1.81 ms | 29.39 s | 842 MiB |
| 1,000,000 | SQLiteStore | 171 | 6.12 ms | 27.22 s | 55.7 MiB |

MemoryStore is the first choice for a scraper whose query index fits in RAM. SQLite
provides persistence with lower peak process memory on this workload; its million-query
index occupied 257 MiB on disk. Both million-query runs emitted 132,900 matching IDs
across the 100 documents, and their first three documents agreed with the query loop.

These synthetic workloads demonstrate that a large query set can run locally. Actual
capacity depends on vocabulary, rule breadth, document length, and the number of
matches returned. MemoryStore also needs room for the old index during replacement.

Raw results: [10,000–100,000 queries](../benchmarks/results/2026-09-06.json),
[one million in memory](../benchmarks/results/2026-09-06-million-memory.json),
[one million in SQLite](../benchmarks/results/2026-09-06-million.json).

## Reproduce

After installing this checkout and its optional LMDB extra:

```sh
python benchmarks/run.py \
  --queries 10000 100000 --documents 100 --tokens 30 300 \
  --backends memory sqlite lmdb --distributions uniform zipf \
  --reference-documents 3 --output benchmarks/results/local.json

python benchmarks/run.py \
  --queries 1000000 --documents 100 --tokens 30 \
  --backends memory sqlite --distributions uniform \
  --reference-documents 3 --output benchmarks/results/million-local.json
```

The runner uses seed 7, a vocabulary of 10,000 tokens, queries with 1–4 AND clauses
and 1–3 OR alternatives per clause, and numeric filters on 20% of queries. `uniform`
draws tokens uniformly; `zipf` weights each vocabulary rank by `1/rank`, generating
many common terms. Documents have 30 or 300 generated tokens and one numeric value.

Every configuration runs in a fresh subprocess. Build time includes seeded query
generation, validation, temporary disk staging, posting construction, and committing
the resulting index. Documents are prepared before timing. Persistent stores are
closed and reopened before matching, and one document warms the index. The measured
matching operation consumes **all returned IDs**, including output construction.
These are warm OS-cache measurements; reopening is not a cold-cache test.

Output includes build time, process peak RSS after build and after matching, database
file bytes (including companions), reopen time, throughput, p50/p95/p99 latency,
and total matching IDs emitted. RSS includes the interpreter, document objects,
mapped pages, and build allocations; it is not the retained Python heap size.
RSS is unavailable on platforms without Python's `resource` module. Database size
is recorded after the first build, not after long-term replacement churn.

The first three documents are also evaluated by an independent straightforward
Boolean/range matcher. IDs and order must agree. The reference query list is allocated
only after Perq's memory measurements, and reference generation is excluded from
reference timing. Increase `--reference-documents` to verify a larger sample. The
test suite separately checks thousands of randomized document/query combinations.

## Backend comparison and common-term workloads

Measured on macOS 26.6.2, ARM64, 12 logical CPUs, Python 3.14.4, using Perq 0.2.0
development code. Raw data with the full environment and all 24 configurations is
checked in at [2026-09-06.json](../benchmarks/results/2026-09-06.json).

Selected **100,000-query, 30-token** results:

| Backend | Uniform docs/s | Zipf docs/s | Uniform build time | Uniform build peak RSS |
|---|---:|---:|---:|---:|
| MemoryStore | 5,801 | 96 | 3.29 s | 132 MiB |
| SQLiteStore | 1,627 | 27 | 2.55 s | 55 MiB |
| LMDBStore | 2,097 | 27 | 2.52 s | 80 MiB |

The distribution makes a major difference. Common terms produce longer posting
lists and more candidates and output matches. Increasing the document length also
increases lookup and verification work. The disk backends read compact match data;
SQLite batches those reads instead of issuing one query for every candidate.

On the three checked documents in the 100,000-query Zipf/30-token case, SQLite
averaged 40.4 ms against 34.8 ms for the straightforward scan; LMDB averaged 40.6 ms
against 37.8 ms. The disk backends were slower than scanning in this case. MemoryStore
averaged 11.8 ms against 34.3 ms. Indexing is most useful when it excludes substantial
work; persistence and high output counts can erase that advantage.

Interpret tail latencies cautiously: each case contains only 100 documents and one
timing run, without confidence intervals or control over other machine activity.
Repeat runs on the target deployment hardware before choosing a capacity target.
The raw report includes the simple scan timing on the same checked documents; compare
those paired means rather than claiming a speedup from different workloads.

## Build memory and stress experiments

Builds stage data in a temporary SQLite file and keep a vocabulary frequency map plus
one term posting list in memory. The full query/posting collection is not retained
as Python tuples for disk backends. Actual memory still grows with vocabulary size,
the largest posting list, database caches, and results. MemoryStore holds its finished
index and needs additional space for the previous generation during replacement.

For intentionally broad rules, pass `--distributions broad`, which limits both query
and document terms to 20 possible tokens. Use longer documents via `--tokens 1000`.
This can be expensive: returning most of the saved query IDs necessarily requires
work and output proportional to query count. Numeric-only rules similarly require
per-document evaluation of each such filter.

## Comparisons and remaining evidence

These results compare the three embedded backends and a simple Boolean scan.
They do not benchmark Elasticsearch percolator, Lucene Monitor, Aho–Corasick,
natural-language retrieval, or semantic matching. Those tools have different matching
capabilities and operational costs; compare equivalent query subsets and include
transport and indexing overhead where they are part of the application workload.

A useful next external validation is a real alert or routing workload with its own
analyzer, query changes, document-length distribution, and service latency budget.
Keep representative positive and negative examples and report the break-even point
between indexing once and repeatedly scanning the full query list.
