"""Streaming JSONL interface for scripts and coding agents."""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import nullcontext
from importlib.metadata import version

from . import Document, LMDBStore, Query, QueryMatcher, SQLiteStore, index


def _records(path):
    stream = nullcontext(sys.stdin) if path == "-" else open(path, encoding="utf-8")
    with stream as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("expected a JSON object")
                yield line_number, record
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc


def _parse(factory, record, path, line):
    try:
        return factory(record)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{path}:{line}: {exc}") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description="Match documents against saved Boolean queries.")
    parser.add_argument("--version", action="version", version=version("perq"))
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "match", "inspect"):
        command = commands.add_parser(name)
        command.add_argument("--index", required=True, help="persistent index file")
        command.add_argument("--backend", choices=("sqlite", "lmdb"), default="sqlite")
        command.add_argument(
            "--map-size",
            type=int,
            default=1 << 30,
            help="LMDB address-space reservation in bytes (default: 1 GiB)",
        )
        if name == "build":
            command.add_argument("--queries", default="-", help="query JSONL file, or - for stdin")
            command.add_argument("--temp-dir", help="directory for disk-backed index staging")
        elif name == "match":
            command.add_argument(
                "--documents", default="-", help="document JSONL file, or - for stdin"
            )
    args = parser.parse_args(argv)
    try:
        options = {"readmode": args.command != "build"}
        factory = SQLiteStore
        if args.backend == "lmdb":
            factory = LMDBStore
            options["map_size"] = args.map_size
        with factory(args.index, **options) as store:
            if args.command == "build":
                count = 0

                def queries():
                    nonlocal count
                    for line, record in _records(args.queries):
                        query = _parse(Query.from_dict, record, args.queries, line)
                        count += 1
                        yield query

                index(queries(), store, temp_dir=args.temp_dir)
                print(
                    json.dumps({"indexed_queries": count, "backend": args.backend}), file=sys.stderr
                )
            elif args.command == "match":
                matcher = QueryMatcher(store)
                for ordinal, (line, record) in enumerate(_records(args.documents)):
                    document = _parse(Document.from_dict, record, args.documents, line)
                    print(
                        json.dumps(
                            {
                                "id": record.get("id", ordinal),
                                "matches": list(matcher.matches(document)),
                            },
                            ensure_ascii=True,
                        )
                    )
            else:
                for query in store.queries():
                    print(json.dumps(query.to_dict(), ensure_ascii=True))
    except Exception as exc:
        print(f"perq: {exc}", file=sys.stderr)
        return 2
    return 0
