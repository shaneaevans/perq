"""Validated, JSON-serializable queries and documents."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

MAX_CLAUSES = 64
QueryId = int | str


def tokenize(text: str) -> tuple[str, ...]:
    """NFKC-normalize, casefold, and extract Unicode word tokens."""
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return tuple(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def _number(value: Any) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _terms(values) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("terms must be a sequence of strings, not a string")
    try:
        result = tuple(values)
    except TypeError as exc:
        raise ValueError("terms must be an iterable of strings") from exc
    if any(not isinstance(t, str) or not t for t in result):
        raise ValueError("each term must be a non-empty string")
    return result


def _id(value):
    if type(value) not in (int, str) or (isinstance(value, str) and not value):
        raise ValueError("id must be an integer or a non-empty string")


def _json_keys(value):
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            raise ValueError("JSON object keys must be strings")
        for item in value.values():
            _json_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _json_keys(item)


@dataclass(frozen=True)
class RangeFilter:
    """A numeric range; use gt/gte and lt/lte for explicit boundaries."""

    field: str
    gt: int | float | None = None
    gte: int | float | None = None
    lt: int | float | None = None
    lte: int | float | None = None

    def __post_init__(self):
        if not isinstance(self.field, str) or not self.field:
            raise ValueError("filter field must be a non-empty string")
        bounds = (self.gt, self.gte, self.lt, self.lte)
        if all(v is None for v in bounds):
            raise ValueError("a range filter needs at least one bound")
        if any(v is not None and not _number(v) for v in bounds):
            raise ValueError("range bounds must be finite numbers")
        if self.gt is not None and self.gte is not None:
            raise ValueError("choose gt or gte, not both")
        if self.lt is not None and self.lte is not None:
            raise ValueError("choose lt or lte, not both")
        lower = self.gt if self.gt is not None else self.gte
        upper = self.lt if self.lt is not None else self.lte
        if lower is not None and upper is not None:
            if lower > upper or (lower == upper and (self.gt is not None or self.lt is not None)):
                raise ValueError("range is empty or reversed")

    def accepts(self, values) -> bool:
        return any(
            (self.gt is None or v > self.gt)
            and (self.gte is None or v >= self.gte)
            and (self.lt is None or v < self.lt)
            and (self.lte is None or v <= self.lte)
            for v in values
        )

    def to_dict(self) -> dict:
        return {k: v for k, v in vars(self).items() if v is not None}


@dataclass(frozen=True, init=False)
class Query:
    query_id: QueryId
    search_terms: tuple[tuple[str, ...], ...]
    filters: tuple[RangeFilter, ...]
    _metadata_json: str

    def __init__(self, query_id: QueryId, search_terms=(), *, filters=(), metadata=None):
        _id(query_id)
        if isinstance(search_terms, (str, bytes)):
            raise ValueError("search_terms must be a sequence of OR clauses")
        clauses = tuple(tuple(dict.fromkeys(_terms(group))) for group in search_terms)
        if len(clauses) > MAX_CLAUSES:
            raise ValueError(f"queries are limited to {MAX_CLAUSES} AND clauses")
        if any(not group for group in clauses):
            raise ValueError("OR clauses cannot be empty")
        filters = tuple(filters)
        if any(not isinstance(f, RangeFilter) for f in filters):
            raise ValueError("filters must contain RangeFilter objects")
        if not clauses and not filters:
            raise ValueError("a query needs a clause or a numeric filter")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be a JSON object")
        try:
            _json_keys(metadata)
            payload = json.dumps(metadata or {}, allow_nan=False, ensure_ascii=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must be JSON-serializable with finite numbers") from exc
        # IDs and metadata are independent of the internal integer posting IDs.
        object.__setattr__(self, "query_id", query_id)
        object.__setattr__(self, "search_terms", clauses)
        object.__setattr__(self, "filters", filters)
        object.__setattr__(self, "_metadata_json", payload)

    @property
    def metadata(self) -> dict:
        return json.loads(self._metadata_json)

    @classmethod
    def from_text(cls, query_id: QueryId, text: str, **kwargs) -> Query:
        """Require all normalized words; this does not parse Boolean operators."""
        return cls(query_id, [(term,) for term in tokenize(text)], **kwargs)

    def to_dict(self) -> dict:
        return {
            "id": self.query_id,
            "terms": [list(group) for group in self.search_terms],
            "filters": [f.to_dict() for f in self.filters],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, value: dict) -> Query:
        if not isinstance(value, dict) or set(value) - {"id", "terms", "filters", "metadata"}:
            raise ValueError("query must contain only id, terms, filters, and metadata")
        if "terms" in value and (
            not isinstance(value["terms"], list)
            or any(not isinstance(group, list) for group in value["terms"])
        ):
            raise ValueError("terms must be an array of arrays")
        if "metadata" in value and not isinstance(value["metadata"], dict):
            raise ValueError("metadata must be a JSON object")
        if "filters" in value and not isinstance(value["filters"], list):
            raise ValueError("filters must be an array")
        for spec in value.get("filters", ()):
            if not isinstance(spec, dict) or any(
                key != "field" and not _number(bound) for key, bound in spec.items()
            ):
                raise ValueError("filters must be objects with numeric bounds")
        try:
            return cls(
                value["id"],
                value.get("terms", ()),
                filters=[RangeFilter(**f) for f in value.get("filters", ())],
                metadata=value.get("metadata"),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"invalid query: {exc}") from exc


class Document:
    """Normalized terms and optional multi-valued numeric fields."""

    def __init__(self, terms, *, values=None):
        self.terms = frozenset(_terms(terms))
        if values is not None and not isinstance(values, dict):
            raise ValueError("values must be an object of numeric arrays")
        self.values = {}
        for field, entries in (values or {}).items():
            if not isinstance(field, str) or not field:
                raise ValueError("numeric field names must be non-empty strings")
            if not isinstance(entries, (tuple, list)) or any(not _number(v) for v in entries):
                raise ValueError("numeric fields must contain arrays of finite numbers")
            self.values[field] = tuple(entries)

    @classmethod
    def from_text(cls, text: str, *, values=None) -> Document:
        return cls(tokenize(text), values=values)

    @classmethod
    def from_dict(cls, value: dict) -> Document:
        if not isinstance(value, dict) or set(value) - {"id", "terms", "text", "values"}:
            raise ValueError("document must contain only id, terms or text, and values")
        if ("terms" in value) == ("text" in value):
            raise ValueError("provide exactly one of terms or text")
        if "id" in value:
            _id(value["id"])
        if "terms" in value and not isinstance(value["terms"], list):
            raise ValueError("terms must be an array")
        if "values" in value and not isinstance(value["values"], dict):
            raise ValueError("values must be an object")
        if "text" in value:
            return cls.from_text(value["text"], values=value.get("values"))
        return cls(value["terms"], values=value.get("values"))
