from __future__ import annotations

import csv
import hashlib
import ipaddress
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from faker import Faker

from .generation_plan import _capacity_for_column

MAX_ROWS_PER_FILE = 1_000_000


class GenerationCancelled(Exception):
    pass


def _rng(seed: int, column: str) -> np.random.Generator:
    digest = hashlib.sha256(f"{seed}:{column}".encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "big"))


def prepare_values_for(column, sample: pd.Series, seed: int) -> Callable[[int], list[str]]:
    values = [str(value).strip() for value in sample.tolist() if str(value).strip()]
    rng = _rng(seed, column.name)
    kind = column.semantic_type
    if not values or kind == "null":
        return lambda rows: [""] * rows
    if kind == "constant":
        return lambda rows: [values[0]] * rows
    if kind == "boolean":
        true_value = values[0] if values[0].casefold() in {"true", "yes", "y", "1"} else "true"
        false_value = next((value for value in values if value.casefold() in {"false", "no", "n", "0"}), "false")
        return lambda rows: np.where(rng.choice([True, False], rows), true_value, false_value).tolist()
    if kind in {"numeric", "currency_amount"}:
        nums = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
        low, high = float(nums.min()), float(nums.max())
        decimals = max((len(value.split(".")[-1]) for value in values if "." in value), default=0)
        return lambda rows: [f"{value:.{decimals}f}" if decimals else str(int(value)) for value in rng.uniform(low, high, rows)]
    if kind == "date":
        dates = pd.to_datetime(pd.Series(values), errors="coerce").dropna()
        start = dates.min()
        span = max(1, (dates.max() - start).days + 1)
        return lambda rows: (start + pd.to_timedelta(rng.integers(0, span, rows), unit="D")).strftime("%Y-%m-%d").tolist()
    if kind == "datetime":
        dates = pd.to_datetime(pd.Series(values), errors="coerce").dropna()
        start = dates.min()
        span = max(1, int((dates.max() - start).total_seconds()))
        return lambda rows: (start + pd.to_timedelta(rng.integers(0, span + 1, rows), unit="s")).strftime("%Y-%m-%d %H:%M:%S").tolist()
    if kind == "email":
        return lambda rows: np.char.add(np.char.add("user", rng.integers(0, 10**9, rows).astype(str)), "@example.test").tolist()
    if kind == "phone":
        return lambda rows: [f"+1 555 {int(value):03d} {int(value * 1000) % 10000:04d}" for value in rng.integers(100, 900, rows)]
    if column.categories:
        choices = np.array([str(entry["value"]) for entry in column.categories], dtype=str)
        weights = np.array([entry["fraction"] for entry in column.categories], dtype=float)
        return lambda rows: rng.choice(choices, rows, p=weights / weights.sum()).tolist()
    if kind == "time":
        seconds = [datetime.strptime(value, "%H:%M:%S" if value.count(":") == 2 else "%H:%M").hour * 3600 + datetime.strptime(value, "%H:%M:%S" if value.count(":") == 2 else "%H:%M").minute * 60 + (datetime.strptime(value, "%H:%M:%S").second if value.count(":") == 2 else 0) for value in values]
        return lambda rows: [f"{int(value) // 3600:02d}:{int(value) % 3600 // 60:02d}:{int(value) % 60:02d}" for value in rng.integers(min(seconds), max(seconds) + 1, rows)]
    if kind == "url":
        return lambda rows: np.char.add("https://example.test/item/", rng.integers(0, 10**9, rows).astype(str)).tolist()
    if kind == "uuid":
        return lambda rows: [f"{int(value):032x}"[:8] + "-" + f"{int(value):032x}"[8:12] + "-4" + f"{int(value):032x}"[13:16] + "-a" + f"{int(value):032x}"[17:20] + "-" + f"{int(value):032x}"[20:32] for value in rng.integers(0, 2**63 - 1, rows)]
    faker = Faker()
    faker.seed_instance(int(rng.integers(0, 2**31 - 1)))
    if kind in {"first_name", "person_name"}:
        return lambda rows: [faker.name() for _ in range(rows)]
    if kind == "company":
        return lambda rows: [faker.company() for _ in range(rows)]
    return lambda rows: rng.choice(np.array(values, dtype=str), rows).tolist()


def values_for(column, sample: pd.Series, rows: int, seed: int) -> list[str]:
    return prepare_values_for(column, sample, seed)(rows)


def primary_key_values(column, sample: pd.Series, rows: int, start: int, multiplier: int) -> list[str]:
    values = [str(value).strip() for value in sample.tolist() if str(value).strip()]
    capacity = _capacity_for_column(column)
    positions = [(start + index) // multiplier % capacity for index in range(rows)]
    if column.inferred_type == "numeric" and column.min_value is not None:
        low = int(float(column.min_value))
        return [str(low + position) for position in positions]
    if column.inferred_type == "masked" and column.pattern:
        generated = []
        for position in positions:
            digits = iter(str(position).zfill(column.pattern.count("D")))
            upper = iter("ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 2)
            lower = iter("abcdefghijklmnopqrstuvwxyz" * 2)
            generated.append("".join(next(digits) if char == "D" else next(upper) if char == "U" else next(lower) if char == "L" else char for char in column.pattern))
        return generated
    if column.categories:
        choices = [entry["value"] for entry in column.categories]
        return [str(choices[position % len(choices)]) for position in positions]
    if column.inferred_type == "constant":
        return [values[0]] * rows
    return values_for(column, sample, rows, start + multiplier)


def generate_csv(sample: pd.DataFrame, profile, plan, target: Path, progress: Callable[[int], None] | None = None, cancel_check: Callable[[], bool] | None = None, chunk_callback: Callable[[dict[str, list[str]], int], None] | None = None, max_rows_per_file: int = MAX_ROWS_PER_FILE) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    generated = 0
    part_number = 0
    part_paths: list[Path] = []
    handle = None
    writer = None
    by_name = {column.name: column for column in profile.columns}
    prepared = {name: prepare_values_for(by_name[name], sample[name], plan.seed) for name in sample.columns if name not in plan.primary_keys}
    try:
        while generated < plan.rows:
            if cancel_check and cancel_check():
                raise GenerationCancelled()
            size = min(plan.chunk_size, plan.rows - generated)
            offset = 0
            while offset < size:
                if writer is None or (generated > 0 and generated % max_rows_per_file == 0):
                    if handle:
                        handle.close()
                    part_number += 1
                    part_path = target if plan.rows <= max_rows_per_file else target.with_name(f"{target.stem}_part_{part_number}{target.suffix}")
                    handle = part_path.open("w", newline="", encoding="utf-8")
                    writer = csv.writer(handle)
                    writer.writerow(list(sample.columns))
                    part_paths.append(part_path)
                part_remaining = max_rows_per_file - (generated % max_rows_per_file)
                write_size = min(size - offset, part_remaining)
                chunk = {}
                multiplier = 1
                for name in plan.primary_keys:
                    chunk[name] = primary_key_values(by_name[name], sample[name], write_size, generated, multiplier)
                    multiplier *= _capacity_for_column(by_name[name])
                for name in sample.columns:
                    if name not in chunk:
                        chunk[name] = prepared[name](write_size)
                writer.writerows(zip(*(chunk[name] for name in sample.columns)))
                generated += write_size
                offset += write_size
                if progress:
                    progress(generated)
                if chunk_callback:
                    chunk_callback(chunk, write_size)
                if cancel_check and cancel_check():
                    raise GenerationCancelled()
    finally:
        if handle:
            handle.close()
    return {"rows": generated, "path": str(part_paths[0]), "paths": [str(path) for path in part_paths]}
