# Perq

**Match scraped documents against large sets of saved search queries in a single
Python process.** Build the query index once, then match each extracted product,
listing, job, or article as it arrives. Matching runs as a local function call inside
your scraper, with no search service to deploy or network request per document.

Perq, formerly PSearch, is an embedded **percolator** for prospective search,
reverse search, saved-search alerts, and document routing. It uses rare-clause
candidate selection and bitmasks so that each document only needs to complete the
checks for candidate queries. A large saved-query set can be served by one process.
The core package has no runtime dependencies and supports Python 3.11–3.14.

In the checked synthetic benchmarks, one process matched documents against
**100,000 saved queries at 5,801 documents/second**, and against **one million at
599 documents/second**, using MemoryStore. The million-query run used **842 MiB peak
process memory**. These figures cover short, pre-tokenized documents drawn from a
uniform vocabulary; [longer and common-term workloads are reported too](docs/benchmarks.md).

## Install

Install version 0.2.0 from the [GitHub release](https://github.com/shaneaevans/perq/releases/tag/v0.2.0):

```sh
python -m pip install https://github.com/shaneaevans/perq/releases/download/v0.2.0/perq-0.2.0-py3-none-any.whl
```

The distribution and import names are `perq`, distinct from the unrelated `psearch`
chemistry package. PyPI publication is pending. To develop from a source checkout:

```sh
python -m pip install .
# Optional persistent key-value backend:
python -m pip install '.[lmdb]'
```

## Match a scraped item

```python
from perq import Document, MemoryStore, Query, QueryMatcher, RangeFilter, index

# Build once when the scraper starts; reuse this matcher for every item.
with MemoryStore() as store:
    index(
        [
            Query(
                "camera-alert",
                [("sony",), ("a7", "a7iii")],
                filters=[RangeFilter("price_eur", lte=1200)],
            ),
            Query.from_text("lens-alert", "canon lens"),
        ],
        store,
    )
    matcher = QueryMatcher(store)

    # Feed fields already extracted by your scraper.
    document = Document.from_text(
        "Sony A7 III mirrorless camera, used body", values={"price_eur": [950]}
    )
    assert list(matcher.matches(document)) == ["camera-alert"]
```

The first query means **sony AND (a7 OR a7iii) AND price_eur ≤ 1200**.
IDs identify saved searches or subscriptions and can be strings or integers. Results
follow query input order. See [the streaming scraper example](examples/scraping.py)
for matching an iterator of extracted items. Perq handles the matching step; your
scraper handles fetching, extraction, and delivery of alerts.

Use `SQLiteStore("queries.sqlite")` for portable persistence, or optional
`LMDBStore("queries.lmdb")` for read-heavy local indexes. Each `index(...)` call
**atomically replaces the whole query set**. A failed build preserves the old index;
`index([], store)` clears it. This release does not expose incremental updates.

## Match JSONL from a terminal or agent

```sh
perq build --index queries.sqlite --queries examples/queries.jsonl
perq match --index queries.sqlite --documents examples/documents.jsonl
perq inspect --index queries.sqlite
```

`match` emits one JSON object per document:

```json
{"id": "doc-1", "matches": ["data-alert"]}
{"id": "doc-2", "matches": ["python-route", "price-only"]}
{"id": "doc-3", "matches": []}
```

Input defaults to stdin. Diagnostics go to stderr. See the checked
[query](schemas/query.schema.json) and [document](schemas/document.schema.json)
schemas and the [agent usage guide](docs/agent-guide.md).

## Performance and ease of use

Perq is a good fit for scraping workloads that reuse many saved searches as new
items arrive: product and price monitoring, classifieds, job alerts, and article
filtering. Query count alone does not require a separate matching service. Start
with MemoryStore when the index fits in RAM, and reuse it for the lifetime of the
scraping process. Index construction is paid once per query-set replacement.

| Approach | Setup and operation in a Python scraper | Matching cost and tradeoff |
|---|---|---|
| **Perq** | Install a Python package, build from query objects, and call the matcher in the existing process. Core and SQLite need no extra dependencies. | Indexing reduces query evaluation to candidates. MemoryStore measured 0.20 ms per document on the 100,000-query short uniform paired sample, about 142× faster than the loop below. Build time was 3.29 s. |
| **Loop over every query** | A few lines of Python; no index to build or retain. | Evaluates every saved query per item. The same paired sample averaged 28.55 ms. Simple and effective when few queries or documents make indexing unnecessary. |
| **Elasticsearch percolator** | Provision an Elasticsearch service, configure mappings, register queries, and send documents through its client/API. This infrastructure can be shared by multiple applications. | Also indexes queries and selects candidates; requests can batch documents to amortize request costs. Throughput relative to Perq has not been benchmarked. |

The Elasticsearch setup and batching behavior are described in its
[percolator documentation](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-percolate-query).
Perq's direct advantage for a Python scraper is its small deployment and integration
cost. The timings above compare the same three documents against a straightforward
Python matcher; [the benchmark report](docs/benchmarks.md) gives the workload,
sample sizes, and cases where the advantage is smaller.

## Query support

Matching is exact after normalization. There is no semantic similarity, ranking,
stemming, phrase/proximity operator, negation, or general query-string parser.
Queries support up to **64 AND clauses**, each containing one or more OR terms.
Numeric-only queries are supported and evaluated for every document. Match-all
queries and empty OR clauses are rejected.

## Storage and performance

| Backend | Use it for | Dependencies |
|---|---|---|
| `MemoryStore` | First choice inside a scraper when the query index fits in RAM | None |
| `SQLiteStore` | Default persistent index, straightforward deployment and file inspection | Python standard library |
| `LMDBStore` | Persistent key lookups with many local readers | Optional `lmdb` extra |

Disk builds stage queries and sort postings in a temporary SQLite file. They retain
term frequencies and one term's posting list in memory, rather than all posting
tuples. `MemoryStore` additionally retains the finished index and, during replacement,
the old generation. Staging requires temporary disk space. This is not a guarantee
of bounded total memory for every workload.

Performance depends on document length, term distribution, Boolean breadth, and
the number of emitted matches. See [benchmark methodology and results](docs/benchmarks.md)
and the [2026 backend decision](docs/storage.md). Broad queries and common terms
can still require work proportional to the query count.

## Development

```sh
python -m pip install '.[dev,lmdb]'
python -m pytest
ruff check .
ruff format --check .
python -m build
twine check dist/*
```

Documentation examples, CLI behavior, JSON schemas, failure recovery, and randomized
reference comparisons are tested. See [usage](docs/usage.md),
[migration notes](docs/migration.md), [contributing](CONTRIBUTING.md), and the
[changelog](CHANGELOG.md). Licensed under [MIT](LICENSE); contributors are listed in
[AUTHORS](AUTHORS).
