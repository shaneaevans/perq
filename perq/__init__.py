"""Perq: embedded document-to-query matching for Python."""

from .engine import QueryMatcher, index
from .models import Document, Query, RangeFilter, tokenize
from .storage import IndexFormatError, LMDBStore, MemoryStore, SQLiteStore

__all__ = [
    "Document",
    "Query",
    "RangeFilter",
    "QueryMatcher",
    "index",
    "tokenize",
    "IndexFormatError",
    "MemoryStore",
    "SQLiteStore",
    "LMDBStore",
]
