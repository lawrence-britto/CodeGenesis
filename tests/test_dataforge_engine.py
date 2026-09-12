import json
from pathlib import Path

import pandas as pd

from engine.test_data_forge.generation_plan import analyze_primary_key, build_generation_plan
from engine.test_data_forge.generator_engine import GenerationCancelled, generate_csv, values_for
from engine.test_data_forge.profiler import profile_dataframe
from engine.test_data_forge.test_data_forge import build_synthetic_dataset
from engine.test_data_forge.validator import validate_csv
from app.routers.test_data_forge import resolve_chunk_size


def sample_frame():
    return pd.DataFrame({
        "CUSTOMER_ID": ["1001", "1002", "1003"],
        "COUNTRY": ["IN", "SG", "IN"],
        "EMAIL": ["a@example.com", "b@example.com", "c@example.com"],
        "OPEN_DATE": ["2026-01-01", "2026-01-02", "2026-01-03"],
    })


def test_profile_contains_metrics_and_candidate_key():
    profile = profile_dataframe(sample_frame())
    customer = next(column for column in profile.columns if column.name == "CUSTOMER_ID")
    assert customer.inferred_type == "numeric"
    assert customer.null_percent == 0
    assert customer.uniqueness_percent == 100
    assert customer.candidate_primary_key is True


def test_primary_key_capacity_rejects_impossible_request():
    profile = profile_dataframe(pd.DataFrame({"STATUS": ["A", "B"]}))
    analysis = analyze_primary_key(profile, ["STATUS"], 3)
    assert analysis.sufficient is False
    assert analysis.capacity == 2
    assert analysis.warnings


def test_zero_primary_keys_are_allowed():
    profile = profile_dataframe(sample_frame())
    analysis = analyze_primary_key(profile, [], 25)
    assert analysis.sufficient is True
    plan, _ = build_generation_plan(profile, [], 25, seed=7, chunk_size=10)
    assert plan.primary_keys == []


def test_chunk_size_uses_rows_for_small_generations():
    assert resolve_chunk_size(99999, 500000) == 99999
    assert resolve_chunk_size(100000, 250000) == 250000


def test_chunk_size_rejects_unapproved_values():
    try:
        resolve_chunk_size(100000, 125000)
    except ValueError:
        pass
    else:
        raise AssertionError("Expected invalid chunk size to be rejected")


def test_large_csv_validation_skips_full_row_set(tmp_path, monkeypatch):
    output = tmp_path / "large.csv"
    output.write_text("id,value\n1,a\n2,b\n", encoding="utf-8")
    monkeypatch.setattr("engine.test_data_forge.validator.FULL_ROW_VALIDATION_MAX_BYTES", 1)
    report = validate_csv(output, [], source_row_count=2, chunk_size=1)
    assert report["duplicate_rows_checked"] is False


def test_same_seed_and_plan_produce_same_chunked_csv(tmp_path):
    sample = sample_frame()
    profile = profile_dataframe(sample)
    plan, _ = build_generation_plan(profile, ["CUSTOMER_ID"], 25, seed=20260911, chunk_size=7)
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    generate_csv(sample, profile, plan, first)
    generate_csv(sample, profile, plan, second)
    assert first.read_bytes() == second.read_bytes()
    generated = pd.read_csv(first, dtype=str)
    assert generated["CUSTOMER_ID"].is_unique
    assert len(generated) == 25


def test_generation_can_be_cancelled_between_chunks(tmp_path):
    sample = sample_frame()
    profile = profile_dataframe(sample)
    plan, _ = build_generation_plan(profile, [], 25, seed=20260911, chunk_size=7)
    target = tmp_path / "cancelled.csv"
    generated = []

    def progress(rows):
        generated.append(rows)

    def cancel_check():
        return bool(generated)

    try:
        generate_csv(sample, profile, plan, target, progress, cancel_check)
    except GenerationCancelled:
        pass
    else:
        raise AssertionError("Expected generation cancellation")
    assert generated == [7]


def test_generation_splits_files_at_configured_row_limit(tmp_path):
    sample = sample_frame()
    profile = profile_dataframe(sample)
    plan, _ = build_generation_plan(profile, [], 25, seed=20260911, chunk_size=7)
    target = tmp_path / "generated_test_data.csv"
    result = generate_csv(sample, profile, plan, target, max_rows_per_file=10)
    parts = [pd.read_csv(path, dtype=str) for path in result["paths"]]
    assert [len(part) for part in parts] == [10, 10, 5]
    assert [Path(path).name for path in result["paths"]] == [
        "generated_test_data_part_1.csv",
        "generated_test_data_part_2.csv",
        "generated_test_data_part_3.csv",
    ]


def test_legacy_builder_preserves_public_contract():
    result, rows, warning = build_synthetic_dataset(sample_frame(), ["CUSTOMER_ID"], 10, seed=11)
    assert warning is None
    assert rows == 10
    assert result["CUSTOMER_ID"].is_unique


def test_profiler_recognizes_extended_common_types():
    sample = pd.DataFrame({
        "ACTIVE": ["true", "false", "true"],
        "CREATED_AT": ["2026-01-01 10:00:00", "2026-01-01 11:00:00", "2026-01-01 12:00:00"],
        "RUN_TIME": ["10:15:00", "11:30:00", "12:45:00"],
        "CLIENT_IP": ["192.168.1.1", "192.168.1.2", "192.168.1.3"],
        "DETAILS": ['{"tier":"A"}', '{"tier":"B"}', '{"tier":"A"}'],
    })
    profile = profile_dataframe(sample)
    assert [column.inferred_type for column in profile.columns] == ["boolean", "datetime", "time", "ipv4", "json"]


def test_extended_types_generate_parseable_values():
    sample = pd.DataFrame({
        "ACTIVE": ["true", "false"],
        "CREATED_AT": ["2026-01-01 10:00:00", "2026-01-01 11:00:00"],
        "RUN_TIME": ["10:15:00", "11:30:00"],
        "CLIENT_IP": ["192.168.1.1", "192.168.1.2"],
        "DETAILS": ['{"tier":"A"}', '{"tier":"B"}'],
    })
    profile = profile_dataframe(sample)
    generated = {column.name: values_for(column, sample[column.name], 20, 7) for column in profile.columns}
    assert set(generated["ACTIVE"]) <= {"true", "false"}
    assert all(pd.to_datetime(value) for value in generated["CREATED_AT"])
    assert all(len(value) == 8 for value in generated["RUN_TIME"])
    assert all(value.startswith("192.168.1.") for value in generated["CLIENT_IP"])
    assert all(isinstance(json.loads(value), dict) for value in generated["DETAILS"])
