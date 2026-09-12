from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ColumnProfile:
    name: str
    inferred_type: str
    semantic_type: str
    row_count: int
    null_count: int
    null_percent: float
    distinct_count: int
    uniqueness_percent: float
    min_value: str | None = None
    max_value: str | None = None
    pattern: str | None = None
    date_formats: list[str] = field(default_factory=list)
    categories: list[dict[str, Any]] = field(default_factory=list)
    sample_values: list[str] = field(default_factory=list)
    confidence: float = 1.0
    candidate_primary_key: bool = False


@dataclass
class DatasetProfile:
    profile_id: str
    source_filename: str
    source_hash: str
    row_count: int
    column_count: int
    columns: list[ColumnProfile]
    relationships: list[dict[str, Any]] = field(default_factory=list)
    profile_version: str = "1.0"


@dataclass
class PrimaryKeyAnalysis:
    columns: list[str]
    capacity: int
    requested_rows: int
    sufficient: bool
    warnings: list[str] = field(default_factory=list)


@dataclass
class ColumnStrategy:
    name: str
    strategy: str
    reason: str
    rule_ids: list[str] = field(default_factory=list)


@dataclass
class GenerationPlan:
    plan_id: str
    profile_id: str
    profile_hash: str
    rows: int
    seed: int
    chunk_size: int
    primary_keys: list[str]
    columns: dict[str, ColumnStrategy]
    created_at: str
    plan_version: str = "1.0"


def to_dict(value: Any) -> dict[str, Any]:
    return asdict(value)
