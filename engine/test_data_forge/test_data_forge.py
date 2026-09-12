from __future__ import annotations

from io import BytesIO

import pandas as pd

from .generation_plan import build_generation_plan
from .generator_engine import primary_key_values, values_for
from .profiler import _derive_mask, _mask, infer_column, profile_dataframe


def read_sample_csv(raw: bytes) -> pd.DataFrame:
    return pd.read_csv(BytesIO(raw), dtype=str, keep_default_na=False)


def build_synthetic_dataset(sample: pd.DataFrame, pk_cols: list[str], rows: int, seed: int = 42) -> tuple[pd.DataFrame, int, str | None]:
    profile = profile_dataframe(sample)
    try:
        plan, _ = build_generation_plan(profile, pk_cols, rows, seed=seed, chunk_size=max(rows, 1))
    except ValueError as error:
        return pd.DataFrame(columns=sample.columns), 0, str(error)
    by_name = {column.name: column for column in profile.columns}
    data = {}
    multiplier = 1
    for name in pk_cols:
        data[name] = primary_key_values(by_name[name], sample[name], rows, 0, multiplier)
        multiplier *= max(1, len(set(str(value).strip() for value in sample[name] if str(value).strip())))
    for name in sample.columns:
        if name not in data:
            data[name] = values_for(by_name[name], sample[name], rows, plan.seed)
    return pd.DataFrame(data), rows, None
