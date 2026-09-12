import re
from collections import Counter
from pathlib import Path
from datetime import date

COUNTRY_CODES = ("AE", "BD", "BH", "BN", "CN", "FD", "GH", "HK", "ID", "IN", "JE", "KE", "MY", "NG", "NP", "SG", "TW", "UG", "VN", "XX", "ZM")
COUNTRY_RE = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(COUNTRY_CODES) + r")(?![A-Za-z0-9])", re.IGNORECASE)
SCHEMA_TABLE_RE = re.compile(r"@([A-Za-z0-9_]+)@\s*\.\s*([A-Za-z_]\w*)")
KNOWN_STAGING_PREFIXES: frozenset[str] = frozenset()


def infer_schema_for_table(table_name: str) -> str:
    name = table_name.strip().upper()
    prefix = name.split("_", 1)[0].lower()
    if prefix in KNOWN_STAGING_PREFIXES:
        return "UAT_TB_DHUB_GSTG_ACTIVE"
    if "REF" in name:
        return "UAT_TB_DHUB_PRIM_REF"
    if re.match(r"(?:W|C|E)_", name):
        return "UAT_TB_DHUB_PRIM_ACTIVE"
    return "UAT_TB_DHUB_GSTG_ACTIVE"


def detect_country_code(filename: str) -> str | None:
    match = COUNTRY_RE.search(Path(filename).stem.upper())
    return match.group(1).upper() if match else None


def resolve_parameters(sql_text: str, overrides: dict | None = None, mapping_filename: str = "", ods_date: str = "", pse_date: str = "", country_code_override: str | None = None, source_db_map: dict | None = None):
    overrides = overrides or {}
    normalized_overrides = {str(key).strip().strip("@").upper(): str(value) for key, value in overrides.items() if value}
    country = (country_code_override or detect_country_code(mapping_filename) or "").upper()
    database_map = {str(key).strip().upper(): str(value).strip() for key, value in (source_db_map or {}).items() if value}
    changes: list[dict] = []
    schema_records: Counter[tuple[str, str]] = Counter()

    def replace_schema(match: re.Match) -> str:
        token, table = match.group(1).upper(), match.group(2)
        value = database_map.get(table.upper()) or infer_schema_for_table(table)
        schema_records[(token, value)] += 1
        return f"{value}.{table}"

    resolved = SCHEMA_TABLE_RE.sub(replace_schema, sql_text)
    values = {
        "ODS_DATE": ods_date or date.today().isoformat(),
        "PSE_DATE": pse_date or date.today().strftime("%Y%m%d"),
        "SOURCE_COUNTRY_CODE": country,
        "ACCS_CTRY_CD": country,
    }
    token_pattern = re.compile(r"@([A-Za-z0-9_]+)@")
    other_records: Counter[tuple[str, str]] = Counter()

    def replace_token(match: re.Match) -> str:
        token = match.group(1).upper()
        if token in normalized_overrides:
            value = normalized_overrides[token]
        elif token.startswith("DATA_SRC_"):
            value = token.removeprefix("DATA_SRC_")
        elif token in values and values[token]:
            value = values[token]
        else:
            return match.group(0)
        other_records[(token, value)] += 1
        return value

    resolved = token_pattern.sub(replace_token, resolved)
    for (token, value), count in sorted(schema_records.items()):
        changes.append({"token": f"@{token}@", "value": value, "occurrences": count, "resolved": True})
    for (token, value), count in sorted(other_records.items()):
        changes.append({"token": f"@{token}@", "value": value, "occurrences": count, "resolved": True})
    return resolved, changes
