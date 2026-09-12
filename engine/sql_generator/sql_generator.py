from pathlib import Path
import re
from typing import Any

import pandas as pd

from .source_sql_parser import parse_source_sql

ALIASES = {
    "Target Object Name": ["Target Object Name", "Target_Object_Name", "TARGET_OBJECT_NAME"],
    "Map Group ID": ["Map Group ID", "Map Group Code", "MAP_GROUP_ID", "Map_Group_ID"],
    "Is DPR as Source": ["Is DPR as Source", "IsDPRasSource", "IS_DPR_AS_SOURCE"],
    "Source Database name": ["Source Database name", "Source Database Name", "SOURCE_DATABASE_NAME"],
    "Source Object Name": ["Source Object Name", "SOURCE_OBJECT_NAME"],
    "Source Attribute Name": ["Source Attribute Name", "SOURCE_ATTRIBUTE_NAME"],
    "Target Attribute Name": ["Target Attribute Name", "TARGET_ATTRIBUTE_NAME"],
    "Data Processing Rule": ["Data Processing Rule", "Data Processing Rules", "DPR", "DATA_PROCESSING_RULE"],
    "Rule Name": ["Rule Name", "RULE_NAME", "RuleName"],
    "Process Type": ["Process Type", "PROCESS_TYPE", "Process Type"],
    "Source Attributes Name": ["Source Attributes Name", "Source Attribute Name", "SOURCE_ATTRIBUTES_NAME"],
    "Map Note": ["Map Note", "MAP_NOTE", "MapNote"],
    "Standardized Map Note": ["Standardized Map Note", "STANDARDIZED_MAP_NOTE", "Standardized_Map_Note", "StdMapNote"],
    "Map Group Code": ["Map Group Code", "MAP_GROUP_CODE", "Map_Group_Code"],
    "Join": ["Join", "JOIN", "join Clause", "JoinClause"],
    "Dependent Map Group": ["Dependent Map Group", "DEPENDENT_MAP_GROUP", "Dependent_Map_Group"],
}


def resolve_col(df: pd.DataFrame, canonical: str) -> str | None:
    columns = {str(column).strip().casefold(): column for column in df.columns}
    for candidate in ALIASES.get(canonical, [canonical]):
        if candidate.casefold() in columns:
            return columns[candidate.casefold()]
    return None


def _get(row, df, canonical: str, default: str = "") -> str:
    column = resolve_col(df, canonical)
    if column is None:
        return default
    value = row.get(column, default)
    if not pd.notna(value):
        return default
    return re.sub(r"_X([0-9A-Fa-f]{4})_", "", str(value)).strip()


def _split(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,\n]+", value or "") if part.strip()]


class SQLGenerator:
    SHEET_S2T = "Source to Target"
    SHEET_DPR = "DPR"
    SHEET_MGC = "Map Group Code"

    def __init__(self, excel_path: str, source_db_name_map: dict | None = None):
        self.excel_path = excel_path
        self._source_db_name_map = {
            str(key).strip(): str(value).strip()
            for key, value in (source_db_name_map or {}).items()
            if str(key).strip() and str(value).strip()
        }
        self.s2t = self.dpr = self.groups = pd.DataFrame()

    def load_excel(self) -> None:
        try:
            workbook = pd.ExcelFile(self.excel_path)
        except PermissionError:
            fixed = Path(self.excel_path).with_name(Path(self.excel_path).stem + "_fixed.xlsx")
            workbook = pd.ExcelFile(fixed if fixed.exists() else self.excel_path)
        actual = {str(name).strip().casefold(): name for name in workbook.sheet_names}
        missing = [name for name in (self.SHEET_S2T, self.SHEET_DPR, self.SHEET_MGC) if name.casefold() not in actual]
        if missing:
            raise ValueError(f"Missing required sheet(s): {', '.join(missing)}; found: {', '.join(workbook.sheet_names)}")
        s2t_name, dpr_name, mgc_name = (actual[name.casefold()] for name in (self.SHEET_S2T, self.SHEET_DPR, self.SHEET_MGC))
        self.s2t = pd.read_excel(self.excel_path, sheet_name=s2t_name, dtype=str).fillna("")
        raw_dpr = pd.read_excel(self.excel_path, sheet_name=dpr_name, dtype=str).fillna("")
        if raw_dpr.empty:
            self.dpr = raw_dpr
        else:
            header_row = None
            for idx in range(len(raw_dpr)):
                candidate = [str(value).strip() for value in raw_dpr.iloc[idx].tolist()]
                lowered = [v.casefold() for v in candidate]
                if "rule name" in lowered or "process type" in lowered:
                    header_row = idx
                    break
            if header_row is not None:
                self.dpr = raw_dpr.iloc[header_row + 1:].copy()
                self.dpr.columns = [str(value).strip() for value in raw_dpr.iloc[header_row].tolist()]
            else:
                self.dpr = raw_dpr
        self.groups = pd.read_excel(self.excel_path, sheet_name=mgc_name, dtype=str).fillna("")
        for frame in (self.s2t, self.dpr, self.groups):
            frame.columns = [str(column).strip() for column in frame.columns]

    def _raw_join(self, code: str) -> str:
        code_col, join_col = resolve_col(self.groups, "Map Group Code"), resolve_col(self.groups, "Join")
        if not code_col or not join_col:
            return ""
        matches = self.groups[self.groups[code_col].astype(str).str.strip() == code.strip()]
        if matches.empty:
            raise ValueError(f"Map Group Code not found: {code}")
        text = str(matches.iloc[0][join_col] or "").strip()
        if len(text) >= 2 and text[0] == text[-1] == '"':
            text = text[1:-1]
        return text.replace("\\n", "\n")

    def _dependent_source_tables(self, code: str) -> set[str]:
        code_col = resolve_col(self.groups, "Map Group Code")
        dependent_col = resolve_col(self.groups, "Dependent Map Group")
        if not code_col or not dependent_col:
            return set()
        matches = self.groups[self.groups[code_col].astype(str).str.strip() == code.strip()]
        if matches.empty:
            return set()
        dependencies = str(matches.iloc[0][dependent_col] or "")
        tables = set()
        for dependency in re.split(r"[\s,]+", dependencies):
            segments = [segment.strip() for segment in dependency.split("~") if segment.strip()]
            if len(segments) >= 2:
                tables.add(segments[-2])
        return tables

    @staticmethod
    def _sanitize_join_text(text: str) -> str:
        if not text:
            return ""
        sanitized = text.strip()
        sanitized = re.sub(r"(?is)(\bSELECT\s+\*)\s+([A-Za-z_][\w.]*)\s+(?=WHERE\b)", r"\1 FROM \2 ", sanitized)
        sanitized = re.sub(r"(?is)\bversion\s+\d+\.\d+\s+start\s*;?\s*$", "", sanitized)
        sanitized = re.sub(r"(?i)\bFROM(?=[A-Z_])", "FROM ", sanitized)
        sanitized = re.sub(r"(?i)\bJOIN(?=[A-Z_])", "JOIN ", sanitized)
        sanitized = re.sub(r"(?i)\bFROM\s*FROM\b", "FROM", sanitized)
        sanitized = re.sub(r"(?i)\bFROM\s*([A-Z_][A-Z0-9_]*)\b(?=\s|$)", r"FROM \1", sanitized)
        sanitized = re.sub(r"(?i)\bJOIN\s*([A-Z_][A-Z0-9_]*)\b(?=\s|$)", r"JOIN \1", sanitized)
        sanitized = re.sub(r"(?im)^\s*SELECT\s*$", "SELECT *", sanitized)
        sanitized = re.sub(r"\s*=\s*", " = ", sanitized)
        sanitized = re.sub(r"\n\s*\n+", "\n", sanitized)
        return sanitized.strip()

    @staticmethod
    def _filter_join_tables(text: str, source_tables: set[str]) -> str:
        if not text:
            return ""
        allowed = {str(table).strip().upper() for table in source_tables if str(table).strip()}
        if not allowed:
            return text.strip()
        parts = re.split(r"(?i)(?=\b(?:LEFT|RIGHT|INNER|FULL|CROSS)\s+JOIN\b)", text.strip())
        kept = []
        for part in parts:
            if not part.strip():
                continue
            match = re.search(r"(?is)\b(?:FROM|JOIN)\s+(?:\(\s*SELECT\b.*?\bFROM\s+)?([A-Za-z_][\w.]*)\b", part)
            if not match:
                continue
            table = match.group(1).upper()
            if table in allowed:
                kept.append(part.strip())
        filtered = "\n".join(kept).strip()
        return filtered

    @staticmethod
    def _enrich_join(text: str, source_tables: set[str]) -> str:
        text = SQLGenerator._sanitize_join_text(text)
        text = SQLGenerator._filter_join_tables(text, source_tables)
        for table in sorted(source_tables, key=len, reverse=True):
            text = re.sub(rf"\b(FROM|JOIN)\s*({re.escape(table)})\b", rf"\1 \2", text, flags=re.IGNORECASE)
        if text and not re.match(r"^\s*FROM\b", text, re.IGNORECASE):
            text = "FROM\n" + text
        return text.strip()

    @staticmethod
    def _coalesce_transform_expression(note: str, source_attr: str, source_ref: str, target_attr: str) -> str:
        note = (note or "").strip()
        if not note:
            return ""
        expr = note
        for token in [source_attr, source_attr.upper(), source_attr.lower()]:
            if token:
                expr = re.sub(rf"(?<![\w.]){re.escape(token)}(?![\w.])", source_ref, expr, flags=re.IGNORECASE)

        attr_norm = (source_attr or target_attr or "").upper()
        if any(token in attr_norm for token in ["EMAIL", "MAIL"]):
            if "LOWER" in expr.upper() or "TRIM" in expr.upper():
                return expr
            return f"LOWER(TRIM({source_ref}))"
        if any(token in attr_norm for token in ["CURY", "CTRY", "LANG", "STAT", "SEGMENT", "TYPE", "SROGT", "CODE", "GENDER", "RISK", "FLAG", "ID"]):
            if "UPPER" in expr.upper():
                return expr
            return f"UPPER({source_ref})"
        if any(token in attr_norm for token in ["DATE", "DT", "BTH", "MRGD"]):
            if "CAST" in expr.upper():
                return expr
            return f"CAST({source_ref} AS DATE)"
        if any(token in attr_norm for token in ["AMT", "BAL", "SCORE", "RANK"]):
            if "CAST" in expr.upper():
                return expr
            return f"CAST({source_ref} AS DECIMAL(18,4))"
        if "TRIM" in expr.upper() or "LOWER" in expr.upper() or "UPPER" in expr.upper() or "CAST" in expr.upper():
            return expr
        return f"TRIM({source_ref})"

    @staticmethod
    def _aliases(join_text: str) -> dict[str, str]:
        aliases = {}
        for match in re.finditer(r"(?is)\b(?:FROM|JOIN)\s+\(\s*select\b.*?\bfrom\s+([A-Za-z_][\w.]*)\b.*?\)\s*(?:AS\s+)?([A-Za-z_]\w*)", join_text):
            aliases[match.group(1).upper()] = match.group(2)
        for match in re.finditer(r"(?is)\b(?:FROM|JOIN)\s+([A-Za-z_][\w.]*)\s+(?:AS\s+)?([A-Za-z_]\w*)", join_text):
            if match.group(2).upper() not in {"ON", "WHERE", "LEFT", "RIGHT", "INNER", "OUTER", "FULL", "CROSS"}:
                aliases.setdefault(match.group(1).upper(), match.group(2))
        return aliases

    @staticmethod
    def _qualified_source(source_obj: str, source_attr: str, join_text: str) -> str:
        source_obj = str(source_obj or "").strip()
        source_attr = str(source_attr or "").strip()
        if not source_obj:
            return source_attr
        aliases = SQLGenerator._aliases(join_text)
        source_alias = aliases.get(source_obj.upper(), source_obj)
        if not source_attr:
            return source_alias
        return f"{source_alias}.{source_attr}"

    def generate(self, target_table: str, map_group_code: str, output_dir: str = "output", source_sql: str | None = None) -> dict[str, Any]:
        if self.s2t.empty:
            self.load_excel()
        target_col, group_col = resolve_col(self.s2t, "Target Object Name"), resolve_col(self.s2t, "Map Group ID")
        if not target_col or not group_col:
            raise ValueError(f"Required S2T columns missing; found: {', '.join(map(str, self.s2t.columns))}")
        rows = self.s2t[(self.s2t[target_col].astype(str).str.strip().str.upper() == target_table.strip().upper()) & (self.s2t[group_col].astype(str).str.strip() == map_group_code.strip())]
        if rows.empty:
            raise ValueError(f"No mapping rows found for target table {target_table} and map group {map_group_code}")
        source_db_map = {}
        for _, row in rows.iterrows():
            tables, databases = _split(_get(row, self.s2t, "Source Object Name")), _split(_get(row, self.s2t, "Source Database name"))
            for index, table in enumerate(tables):
                source_db_map[table] = databases[min(index, len(databases) - 1)] if databases else ""
            source_db_map = {**self._source_db_name_map, **source_db_map}
        source_info = parse_source_sql(source_sql) if source_sql else {"query_prefix": "", "select_columns": [], "select_alias_map": {}}
        warnings = []
        direct, dpr_default, dpr_transform, dpr_details = [], [], [], []
        dpr_rule_col, dpr_note_col = resolve_col(self.dpr, "Rule Name"), resolve_col(self.dpr, "Standardized Map Note") or resolve_col(self.dpr, "Map Note")
        dpr_type_col = resolve_col(self.dpr, "Process Type")
        is_dpr_col = resolve_col(self.s2t, "Is DPR as Source")
        approved_join_tables = set(source_db_map) | self._dependent_source_tables(map_group_code)
        join_clause = self._enrich_join(self._raw_join(map_group_code), approved_join_tables)
        aliases = self._aliases(join_clause)
        for _, row in rows.iterrows():
            target_attr = _get(row, self.s2t, "Target Attribute Name")
            source_obj, source_attr = _get(row, self.s2t, "Source Object Name"), _get(row, self.s2t, "Source Attribute Name")
            is_dpr = is_dpr_col and _get(row, self.s2t, "Is DPR as Source").lower() not in {"", "false", "0", "no", "n"}
            rule = _get(row, self.s2t, "Data Processing Rule")
            if not target_attr:
                continue
            if not is_dpr:
                if source_obj and source_attr and len(_split(source_obj)) == 1:
                    qualified = SQLGenerator._qualified_source(_split(source_obj)[0], source_attr, join_clause)
                    direct.append(f"{qualified} AS {target_attr}")
                elif len(_split(source_obj)) > 1:
                    warnings.append(f"Multiple source tables for {target_attr}; emitted NULL TODO")
                    direct.append(f"NULL /* TODO: confirm source table */ AS {target_attr}")
                elif not source_obj or not source_attr:
                    warnings.append(f"Source mapping missing for {target_attr}; emitted NULL TODO")
                    direct.append(f"NULL /* TODO: confirm source object and attribute */ AS {target_attr}")
                continue
            if not rule or not dpr_rule_col:
                warnings.append(f"DPR rule missing for target {target_attr}")
                dpr_transform.append(f"NULL /* TODO: confirm DPR rule */ AS {target_attr}")
                continue
            candidates = self.dpr[self.dpr[dpr_rule_col].astype(str).str.strip() == rule]
            if candidates.empty:
                candidates = self.dpr[self.dpr[dpr_rule_col].astype(str).str.replace(r"\s+", "", regex=True).str.casefold() == re.sub(r"\s+", "", rule).casefold()]
            if candidates.empty:
                warnings.append(f"DPR rule '{rule}' not found for target '{target_attr}'")
                dpr_transform.append(f"NULL /* TODO: confirm approved DPR rule */ AS {target_attr}")
                continue
            process_type = _get(candidates.iloc[0], self.dpr, "Process Type").upper()
            note = _get(candidates.iloc[0], self.dpr, "Standardized Map Note") or _get(candidates.iloc[0], self.dpr, "Map Note")
            if process_type == "DEFAULT":
                value = note or map_group_code
                if value.endswith("'") and not value.startswith("'"):
                    value = "'" + value
                literal = value if value.startswith("'") and value.endswith("'") else repr(value)
                expression = f"{literal} AS {target_attr}"
                dpr_default.append(expression)
            elif process_type == "TRANSFORM":
                source_ref = SQLGenerator._qualified_source(_split(source_obj)[0] if _split(source_obj) else source_obj, source_attr, join_clause) if source_attr else ""
                expression = SQLGenerator._coalesce_transform_expression(note, source_attr, source_ref, target_attr) if source_attr and source_ref else note
                if not expression:
                    expression = f"NULL /* TODO: confirm DPR transform for {target_attr} */"
                    warnings.append(f"DPR transform missing for target {target_attr}")
                dpr_transform.append(f"{expression} AS {target_attr}")
            dpr_details.append({"target_attr": target_attr, "dpr_rule": rule, "process_type": process_type, "status": "processed"})
        for table in source_db_map:
            if not re.search(rf"\b{re.escape(table)}\b", join_clause, re.IGNORECASE):
                warnings.append(f"Table '{table}' is referenced in S2T but has no explicit JOIN; no join was added")
                join_clause += f"\n/* TODO: add approved JOIN for {table} */"
        mapped_target_aliases = {
            _get(row, self.s2t, "Target Attribute Name").upper()
            for _, row in rows.iterrows()
            if _get(row, self.s2t, "Target Attribute Name")
        }

        def reconcile(expressions):
            kept = []
            for expression in expressions:
                match = re.search(r"\bAS\s+([A-Za-z_]\w*)\s*$", expression, re.IGNORECASE)
                alias = match.group(1).upper() if match else ""
                if alias in source_info.get("select_alias_map", {}):
                    old = source_info["select_alias_map"][alias]
                    if re.sub(r"\s+", "", old).upper() == re.sub(r"\s+", "", expression).upper():
                        continue
                    source_info["select_columns"] = [expression if alias in column.upper() else column for column in source_info.get("select_columns", [])]
                else:
                    kept.append(expression)
            return kept
        if source_sql:
            source_info["select_columns"] = [
                expression for expression in source_info.get("select_columns", [])
                if (match := re.search(r"\bAS\s+([A-Za-z_]\w*)\s*$", expression, re.IGNORECASE))
                and match.group(1).upper() in mapped_target_aliases
            ]
            source_info["select_alias_map"] = {
                alias: expression for alias, expression in source_info.get("select_alias_map", {}).items()
                if alias in mapped_target_aliases
            }
            dpr_default = reconcile(dpr_default)
            direct = reconcile(direct)
            dpr_transform = reconcile(dpr_transform)
        select_columns = source_info.get("select_columns", []) + dpr_default + direct + dpr_transform
        if not select_columns:
            raise ValueError("No SELECT expressions were produced")
        select_columns = list(dict.fromkeys(select_columns))
        sql = (source_info.get("query_prefix", "") + "\n" if source_info.get("query_prefix") else "") + "SELECT\n" + ",\n".join(select_columns) + "\n" + join_clause + "\n"
        segments = map_group_code.split("~")
        filename = (segments[-2] if len(segments) > 1 else segments[0]).lower() + "_raw.sql"
        output_path = Path(output_dir) / "raw_mapping" / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(sql, encoding="utf-8")
        todos = [warning for warning in warnings if "TODO" in warning.upper()]
        return {
            "sql": sql,
            "output_file": str(output_path),
            "mapping_rows": [row.to_dict() for _, row in rows.iterrows()],
            "mapping_row_count": len(rows),
            "select_columns": select_columns,
            "join_text": join_clause,
            "alias_map": aliases,
            "direct_mappings": direct,
            "dpr_default": dpr_default,
            "dpr_transform": dpr_transform,
            "source_db_map": source_db_map,
            "warnings": warnings,
            "todos": todos,
            "target_table": target_table,
            "map_group_code": map_group_code,
            "dpr_details": dpr_details,
            "s2t_summary": [],
            "source_query_prefix": source_info.get("query_prefix", ""),
            "join_changes": [],
            "join_changes_mode": "source_sql" if source_sql else "mapping_only",
            "sql_metadata": {
                "target_table": target_table,
                "map_group_code": map_group_code,
                "select_count": len(select_columns),
                "source_tables": sorted(source_db_map),
                "has_source_sql": bool(source_sql),
                "join_count": len(re.findall(r"\bJOIN\b", join_clause, re.IGNORECASE)),
            },
            "mapping_metadata": {
                "mapped_columns": len(select_columns),
                "direct_columns": len(direct),
                "default_columns": len(dpr_default),
                "transform_columns": len(dpr_transform),
                "dpr_rules_processed": len(dpr_details),
                "warnings_count": len(warnings),
            },
        }
