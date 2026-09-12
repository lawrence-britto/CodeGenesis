from __future__ import annotations

import hashlib
import ipaddress
import re
import uuid
import json
from datetime import datetime

import pandas as pd

from .models import ColumnProfile, DatasetProfile

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
URL = re.compile(r"^https?://", re.I)
PHONE = re.compile(r"^[+()\d][+()\d .-]{6,}$")
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")


def _mask(value: str) -> str:
    return "".join("D" if c.isdigit() else "U" if c.isupper() else "L" if c.islower() else c for c in value)


def _derive_mask(values: list[str]) -> str | None:
    if not values or len({len(value) for value in values}) != 1:
        return None
    masks = [_mask(value) for value in values]
    mask = masks[0]
    return mask if all(value == mask for value in masks) and any(char not in "DUL" for char in mask) else None


def infer_column(series: pd.Series) -> str:
    values = [str(value).strip() for value in series if str(value).strip()]
    if not values:
        return "null"
    if len(set(values)) == 1:
        return "constant"
    if all(value.casefold() in {"true", "false", "yes", "no", "y", "n", "1", "0"} for value in values):
        return "boolean"
    if all(TIME_PATTERN.match(value) for value in values):
        return "time"
    try:
        if all(isinstance(json.loads(value), (dict, list)) for value in values):
            return "json"
    except (TypeError, json.JSONDecodeError):
        pass
    try:
        if all(ipaddress.ip_address(value).version == 4 for value in values):
            return "ipv4"
    except ValueError:
        pass
    numeric = pd.to_numeric(pd.Series(values), errors="coerce")
    if numeric.notna().all():
        return "numeric"
    parsed = pd.to_datetime(pd.Series(values), errors="coerce", format="mixed")
    if parsed.notna().all():
        return "datetime" if any("T" in value or ":" in value for value in values) else "date"
    if all(EMAIL.match(value) for value in values):
        return "email"
    if all(UUID_PATTERN.match(value) for value in values):
        return "uuid"
    if all(URL.match(value) for value in values):
        return "url"
    if all(PHONE.match(value) for value in values):
        return "phone"
    if _derive_mask(values):
        return "masked"
    name = str(series.name).casefold().replace(" ", "_")
    for key in ("first_name", "last_name", "company", "job_title", "address", "city", "country", "postal", "description"):
        if key in name:
            return key
    return "person_name" if "name" in name else "word"


def _date_formats(values: list[str]) -> list[str]:
    formats: list[str] = []
    for value in values[:100]:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
            try:
                datetime.strptime(value, fmt)
                if fmt not in formats:
                    formats.append(fmt)
                break
            except ValueError:
                continue
    return formats


def _semantic_type(name: str, inferred: str) -> str:
    lowered = name.casefold()
    if inferred == "numeric" and any(token in lowered for token in ("amount", "balance", "price", "salary", "value")):
        return "currency_amount"
    if inferred in {"email", "phone", "url", "uuid"}:
        return inferred
    if "postal" in lowered or "zip" in lowered:
        return "postal_code"
    return inferred


def profile_dataframe(sample: pd.DataFrame, source_filename: str = "sample.csv", source_hash: str | None = None) -> DatasetProfile:
    source_hash = source_hash or hashlib.sha256(sample.to_csv(index=False).encode("utf-8")).hexdigest()
    columns: list[ColumnProfile] = []
    row_count = len(sample)
    for name in sample.columns:
        series = sample[name].astype(str)
        values = [value.strip() for value in series.tolist() if value.strip()]
        distinct_count = len(set(values))
        inferred = infer_column(series)
        numeric = pd.to_numeric(pd.Series(values), errors="coerce")
        parsed = pd.to_datetime(pd.Series(values), errors="coerce", format="mixed")
        categories = []
        if values and distinct_count <= min(100, max(20, row_count // 5)):
            counts = pd.Series(values).value_counts(normalize=True)
            categories = [{"value": str(value), "fraction": round(float(fraction), 8)} for value, fraction in counts.items()]
        min_value = max_value = None
        if numeric.notna().all() and len(numeric):
            min_value, max_value = str(numeric.min()), str(numeric.max())
        elif parsed.notna().all() and len(parsed):
            min_value, max_value = str(parsed.min()), str(parsed.max())
        elif values:
            min_value, max_value = min(values), max(values)
        columns.append(ColumnProfile(
            name=str(name), inferred_type=inferred, semantic_type=_semantic_type(str(name), inferred), row_count=row_count,
            null_count=row_count - len(values), null_percent=round((row_count - len(values)) / row_count * 100, 4) if row_count else 0,
            distinct_count=distinct_count, uniqueness_percent=round(distinct_count / len(values) * 100, 4) if values else 0,
            min_value=min_value, max_value=max_value, pattern=_derive_mask(values),
            date_formats=_date_formats(values) if inferred == "date" else [], categories=categories, sample_values=values[:5],
            confidence=1.0 if values else 0.0, candidate_primary_key=bool(values and len(values) == distinct_count and not (row_count - len(values)))
        ))
    return DatasetProfile(f"profile-{uuid.uuid4().hex[:12]}", source_filename, source_hash, row_count, len(columns), columns)
