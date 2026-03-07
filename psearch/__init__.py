"""
Public package exports.
"""

from .pdoc import Document
from .pquery import Query
from .psearch import QueryMatcher, index
from .pstorage import LMDBStore, MemoryStore, SQLiteStore

__all__ = [
    "Document",
    "Query",
    "QueryMatcher",
    "index",
    "LMDBStore",
    "MemoryStore",
    "SQLiteStore",
]
