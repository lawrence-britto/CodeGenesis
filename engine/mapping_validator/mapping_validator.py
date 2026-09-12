from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from engine.mapping_validator.rules import load_secondary_validation_rules
from engine.sql_generator.sql_generator import SQLGenerator, resolve_col

REQUIRED_S2T_COLUMNS = ["Map Group ID", "Source Object Name", "Source Object ID", "Source Attribute Name", "Source Attribute ID", "Target Object Name", "Target Attribute Name"]
IDENTIFIER_COLUMNS = REQUIRED_S2T_COLUMNS
OPTIONAL_COLUMNS = {
    "Data Processing Rule": ["Data Processing Rule", "Data Processing Rules", "DPR", "DATA_PROCESSING_RULE"],
    "Active": ["Active", "Is Active", "Active Flag", "Status", "Mapping Status", "Is Inactive", "Inactive"],
}

@dataclass
class ValidationIssue:
    severity: str
    message: str

@dataclass
class ValidationResult:
    passed: bool
    map_group_count: int
    row_count: int
    issues: list[ValidationIssue] = field(default_factory=list)
    message: str = ""
    map_group_ids: list[str] = field(default_factory=list)
    status: str = "pass"


@dataclass(frozen=True)
class ValidationRule:
    id: str
    name: str
    check: Callable[[pd.DataFrame, dict[str, str | None], dict | None, pd.DataFrame | None], list[ValidationIssue]]


def _matches_exclusion(rule_id: str, rule_title: str, excluded_rule_ids: set[str] | None) -> bool:
    if not excluded_rule_ids:
        return False
    normalized = {str(value).strip() for value in excluded_rule_ids if str(value).strip()}
    return rule_id in normalized or rule_title in normalized or rule_title.replace("_", " ") in normalized


def run_secondary_rule_validation(df: pd.DataFrame, resolved: dict[str, str | None], config: dict | None = None, dpr_df: pd.DataFrame | None = None, excluded_rule_ids: set[str] | None = None, selected_rule_ids: set[str] | None = None) -> list[ValidationIssue]:
    """Secondary review checks are intentionally disabled in the authoritative validation path.

    RAG and the approved markdown catalog remain advisory-only for explanation and guidance;
    the deterministic validator decides the final PASS/FAIL result.
    """
    return []


def validate_mapping_sheet_file(saved_path: str, config: dict, excluded_rule_ids: set[str] | None = None, selected_rule_ids: set[str] | list[str] | tuple[str, ...] | None = None) -> ValidationResult:
    generator = SQLGenerator(saved_path, config.get("source_db_name_map", {}))
    try:
        generator.load_excel()
    except ValueError as exc:
        return ValidationResult(False, 0, 0, [ValidationIssue("error", str(exc))], "Mapping sheet failed structural validation - fix the errors before starting SQL generation", [], "fail")
    df = generator.s2t.copy(); issues = []; resolved = {}
    for name in REQUIRED_S2T_COLUMNS:
        resolved[name] = resolve_col(df, name)
        if not resolved[name]: issues.append(ValidationIssue("error", f"Required column '{name}' not found in the 'Source to Target' sheet"))
    if df.empty:
        issues.append(ValidationIssue("error", "The 'Source to Target' sheet contains no mapping rows"))
        return ValidationResult(False, 0, 0, issues, "Mapping sheet failed structural validation - fix the errors before starting SQL generation", [], "fail")

    def values(column: str) -> pd.Series:
        return df[column].map(lambda value: "" if not pd.notna(value) else str(value).strip())

    def row_numbers(mask: pd.Series) -> str:
        return ", ".join(str(index + 2) for index in df.index[mask])

    def optional_column(name: str) -> str | None:
        columns = {str(column).strip().casefold(): column for column in df.columns}
        return next((columns[candidate.casefold()] for candidate in OPTIONAL_COLUMNS[name] if candidate.casefold() in columns), None)

    groups = set()
    if resolved.get("Map Group ID"):
        group_values = values(resolved["Map Group ID"])
        groups = set(group_values[group_values != ""])
        if not groups: issues.append(ValidationIssue("error", "The workbook contains no usable Map Group IDs"))

    for name in REQUIRED_S2T_COLUMNS:
        column = resolved.get(name)
        if not column:
            continue
        column_values = values(column)
        blank_count = int((column_values == "").sum())
        if blank_count:
            severity = "error"
            issues.append(ValidationIssue(severity, f"{blank_count} row(s) have a blank {name} at Excel row(s) {row_numbers(column_values == '')}"))
        whitespace_count = int(df[column].map(lambda value: pd.notna(value) and str(value) != str(value).strip()).sum())
        if whitespace_count:
            whitespace_rows = df[column].map(lambda value: pd.notna(value) and str(value) != str(value).strip())
            issues.append(ValidationIssue("warning", f"{whitespace_count} row(s) have leading or trailing whitespace in {name} at Excel row(s) {row_numbers(whitespace_rows)}"))

    target = resolved.get("Target Object Name")
    source_object = resolved.get("Source Object Name")
    source_attr = resolved.get("Source Attribute Name")
    target_attr = resolved.get("Target Attribute Name")
    if target and resolved.get("Map Group ID"):
        grouped = df.assign(_group=group_values)
        for group, chunk in grouped[grouped["_group"] != ""].groupby("_group"):
            if chunk[target].map(lambda value: "" if not pd.notna(value) else str(value).strip()).replace("", None).dropna().nunique() > 1:
                issues.append(ValidationIssue("warning", f"Map Group '{group}' maps to more than one target table - verify this is intentional"))

    dpr_column = optional_column("Data Processing Rule")
    if dpr_column:
        rule_column = resolve_col(generator.dpr, "Rule Name")
        approved_rules = set(generator.dpr[rule_column].map(lambda value: str(value).strip()).loc[lambda series: series != ""]) if rule_column else set()
        for rule in sorted(set(values(dpr_column)) - {""}):
            if rule not in approved_rules:
                issues.append(ValidationIssue("warning", f"Data Processing Rule '{rule}' is not present in the approved DPR rulebook at Excel row(s) {row_numbers(values(dpr_column) == rule)}"))

    active_column = optional_column("Active")
    if active_column and resolved.get("Map Group ID") and target and target_attr:
        active_values = values(active_column).str.casefold()
        inactive = active_values.isin({"inactive", "false", "0", "no", "n", "deprecated"})
        keys = values(resolved["Map Group ID"]) + " / " + values(target) + " / " + values(target_attr)
        for key in sorted(set(keys[keys != ""])):
            rows = keys == key
            if rows.any() and (~inactive[rows]).any() and inactive[rows].any():
                issues.append(ValidationIssue("warning", f"Mapping '{key}' has both active and inactive versions"))

    if any(issue.severity == "error" for issue in issues):
        status = "fail"
        passed = False
        message = "Mapping sheet failed structural validation - fix the errors before starting SQL generation"
    else:
        status = "pass"
        passed = True
        message = "Mapping sheet is structurally valid - safe to proceed with SQL generation"

    return ValidationResult(passed, len(groups), len(df), issues, message, sorted(groups), status)
