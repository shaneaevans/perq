"""
Query model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Query:
    query_id: int
    search_terms: list[tuple[str, ...] | list[str]]
    data_dict: dict[str, Any] = field(default_factory=dict)

    def __init__(self, query_id, search_terms, **data_dict):
        self.query_id = query_id
        self.search_terms = search_terms
        self.data_dict = data_dict
