"""Reproducible end-to-end measurements; each case runs in a fresh process."""

from __future__ import annotations

import argparse
import gc
import itertools
import json
import math
import os
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path

from perq import (
    Document,
    LMDBStore,
    MemoryStore,
    Query,
    QueryMatcher,
    RangeFilter,
    SQLiteStore,
    index,
)


def _terms(rng, count, vocab, distribution):
    if distribution == "uniform":
        return [f"t{rng.randrange(vocab)}" for _ in range(count)]
    if distribution == "broad":
        return [f"t{rng.randrange(min(20, vocab))}" for _ in range(count)]
    # A truncated Zipf distribution, with cumulative weights reused across calls.
    weights = _zipf_weights(vocab)
    return [f"t{i}" for i in rng.choices(range(vocab), cum_weights=weights, k=count)]


@lru_cache(maxsize=4)
def _zipf_weights(vocab):
    return list(itertools.accumulate(1 / (i + 1) for i in range(vocab)))


def make_queries(count, vocab, distribution, seed):
    rng = random.Random(seed)
    for qid in range(count):
        clauses = [
            _terms(rng, rng.randint(1, 3), vocab, distribution) for _ in range(rng.randint(1, 4))
        ]
        filters = [RangeFilter("price", gte=25, lt=75)] if rng.random() < 0.2 else []
        yield Query(qid, clauses, filters=filters)


def make_documents(count, tokens, vocab, distribution, seed):
    rng = random.Random(seed + 1)
    return [
        Document(_terms(rng, tokens, vocab, distribution), values={"price": [rng.randrange(100)]})
        for _ in range(count)
    ]


def reference_matches(queries, document):
    """Independent Boolean/range oracle for this generated workload."""
    return [
        q.query_id
        for q in queries
        if all(any(term in document.terms for term in group) for group in q.search_terms)
        and (not q.filters or 25 <= document.values["price"][0] < 75)
    ]


def peak_rss():
    try:
        import resource
    except ImportError:
        return None
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss if sys.platform == "darwin" else rss * 1024


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def measure(config):
    docs = make_documents(
        config["documents"],
        config["tokens"],
        config["vocab"],
        config["distribution"],
        config["seed"],
    )
    with tempfile.TemporaryDirectory(prefix="perq-benchmark-") as directory:
        path = Path(directory) / "index"
        backend = config["backend"]
        store = (
            MemoryStore()
            if backend == "memory"
            else (SQLiteStore(path) if backend == "sqlite" else LMDBStore(path, map_size=8 << 30))
        )
        try:
            start = time.perf_counter()
            index(
                make_queries(
                    config["queries"], config["vocab"], config["distribution"], config["seed"]
                ),
                store,
            )
            build_seconds = time.perf_counter() - start
            build_peak_rss = peak_rss()
            reopen_seconds = None
            if backend != "memory":
                store.close()
                start = time.perf_counter()
                store = (
                    SQLiteStore(path, readmode=True)
                    if backend == "sqlite"
                    else LMDBStore(path, readmode=True, map_size=8 << 30)
                )
                reopen_seconds = time.perf_counter() - start
            matcher = QueryMatcher(store)
            # Warm the index explicitly; do not call this a cold-cache measurement.
            list(matcher.matches(docs[0]))
            samples = []
            hits = 0
            for doc in docs:
                start = time.perf_counter()
                count = sum(1 for _ in matcher.matches(doc))
                samples.append(time.perf_counter() - start)
                hits += count
            match_peak_rss = peak_rss()
            file_bytes = (
                sum(f.stat().st_size for f in Path(directory).glob("index*"))
                if backend != "memory"
                else None
            )
            # Build the naive reference only after recording the library's memory use.
            reference = list(
                make_queries(
                    config["queries"], config["vocab"], config["distribution"], config["seed"]
                )
            )
            checked = min(config["reference_documents"], len(docs))
            reference_seconds = []
            for doc in docs[:checked]:
                start = time.perf_counter()
                expected = reference_matches(reference, doc)
                reference_seconds.append(time.perf_counter() - start)
                assert list(matcher.matches(doc)) == expected, "reference result mismatch"
            del reference
            gc.collect()
            return config | {
                "build_seconds": build_seconds,
                "build_includes_query_generation": True,
                "build_peak_rss_bytes": build_peak_rss,
                "match_peak_rss_bytes": match_peak_rss,
                "index_file_bytes": file_bytes,
                "reopen_seconds": reopen_seconds,
                "documents_per_second": len(docs) / sum(samples),
                "latency_p50_ms": statistics.median(samples) * 1000,
                "latency_p95_ms": percentile(samples, 0.95) * 1000,
                "latency_p99_ms": percentile(samples, 0.99) * 1000,
                "matching_query_ids_emitted": hits,
                "reference_documents_checked": checked,
                "reference_mean_ms": statistics.mean(reference_seconds) * 1000 if checked else None,
                "matching_mean_ms_on_reference_documents": statistics.mean(samples[:checked]) * 1000
                if checked
                else None,
            }
        finally:
            store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", nargs="+", type=int, default=[10_000, 100_000])
    parser.add_argument(
        "--backends", nargs="+", choices=["memory", "sqlite", "lmdb"], default=["memory", "sqlite"]
    )
    parser.add_argument("--documents", type=int, default=100)
    parser.add_argument("--tokens", nargs="+", type=int, default=[30, 300])
    parser.add_argument("--vocab", type=int, default=10_000)
    parser.add_argument(
        "--distributions",
        nargs="+",
        choices=["uniform", "zipf", "broad"],
        default=["uniform", "zipf"],
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--reference-documents", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(measure(json.loads(args.worker))))
        return
    if (
        min(*args.queries, *args.tokens, args.documents, args.vocab) < 1
        or args.reference_documents < 0
    ):
        parser.error("counts must be positive, and reference-documents cannot be negative")
    report = {
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "package_version": version("perq"),
        },
        "method": "fresh process per case; warm reads; input generation included only in build; RSS recorded before reference allocation",
        "results": [],
    }
    for count, backend, tokens, distribution in itertools.product(
        args.queries, args.backends, args.tokens, args.distributions
    ):
        config = {
            "queries": count,
            "backend": backend,
            "tokens": tokens,
            "distribution": distribution,
            "documents": args.documents,
            "vocab": args.vocab,
            "seed": args.seed,
            "reference_documents": args.reference_documents,
        }
        run = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker", json.dumps(config)],
            capture_output=True,
            text=True,
            check=True,
        )
        result = json.loads(run.stdout)
        report["results"].append(result)
        print(
            f"{count:,} queries / {backend} / {tokens} tokens / {distribution}: "
            f"{result['documents_per_second']:,.0f} docs/s; build {result['build_seconds']:.2f}s",
            file=sys.stderr,
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2) + "\n")
    if not args.output:
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
