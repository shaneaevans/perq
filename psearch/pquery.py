"""
Query model.
"""

from __future__ import annotations

from typing import Any


class Query:
    __slots__ = ("query_id", "search_terms", "data_dict")

    def __init__(self, query_id: int, search_terms, **data_dict: Any):
        self.query_id = query_id
        self.search_terms = search_terms
        self.data_dict = data_dict

    def __repr__(self) -> str:
        return (
            f"Query(query_id={self.query_id!r}, "
            f"search_terms={self.search_terms!r}, data_dict={self.data_dict!r})"
        )
