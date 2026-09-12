from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .models import ColumnStrategy, DatasetProfile, GenerationPlan, PrimaryKeyAnalysis


def _capacity_for_column(column) -> int:
    if column.inferred_type == "constant":
        return 1
    if column.inferred_type == "numeric":
        return 10**12
    if column.inferred_type == "masked" and column.pattern:
        return max(1, 10 ** column.pattern.count("D") * 26 ** (column.pattern.count("U") + column.pattern.count("L")))
    if column.categories:
        return len(column.categories)
    return 10**12


def analyze_primary_key(profile: DatasetProfile, columns: list[str], requested_rows: int) -> PrimaryKeyAnalysis:
    by_name = {column.name: column for column in profile.columns}
    warnings: list[str] = []
    if not 0 <= len(columns) <= 5:
        warnings.append("Primary key must contain between 0 and 5 columns.")
    if len(set(columns)) != len(columns):
        warnings.append("Primary key columns must be distinct.")
    missing = [column for column in columns if column not in by_name]
    if missing:
        warnings.append(f"Unknown primary key columns: {', '.join(missing)}")
    if warnings:
        return PrimaryKeyAnalysis(columns, 0, requested_rows, False, warnings)
    if not columns:
        return PrimaryKeyAnalysis(columns, 0, requested_rows, True, warnings)
    capacity = 1
    for name in columns:
        capacity = min(10**18, capacity * _capacity_for_column(by_name[name]))
    sufficient = capacity >= requested_rows
    if not sufficient:
        warnings.append(f"Requested {requested_rows:,} rows exceed deterministic primary-key capacity of {capacity:,}.")
    return PrimaryKeyAnalysis(columns, capacity, requested_rows, sufficient, warnings)


def _strategy(column) -> ColumnStrategy:
    mapping = {"constant": "constant", "numeric": "bounded_numeric", "currency_amount": "bounded_decimal", "date": "date_range", "datetime": "datetime_range", "time": "time_range", "boolean": "boolean", "ipv4": "ipv4_range", "json": "json_sample", "email": "email", "phone": "phone", "url": "url", "uuid": "uuid", "masked": "masked_string"}
    strategy = mapping.get(column.semantic_type, "weighted_category" if column.categories else "faker_word")
    return ColumnStrategy(column.name, strategy, f"Selected from deterministic profile type '{column.semantic_type}'.")


def build_generation_plan(profile: DatasetProfile, primary_keys: list[str], rows: int, seed: int, chunk_size: int = 100_000) -> tuple[GenerationPlan, PrimaryKeyAnalysis]:
    analysis = analyze_primary_key(profile, primary_keys, rows)
    if not analysis.sufficient:
        raise ValueError("; ".join(analysis.warnings))
    strategies = {column.name: _strategy(column) for column in profile.columns}
    plan = GenerationPlan(f"plan-{uuid.uuid4().hex[:12]}", profile.profile_id, profile.source_hash, rows, seed, chunk_size, primary_keys, strategies, datetime.now(timezone.utc).isoformat())
    return plan, analysis
