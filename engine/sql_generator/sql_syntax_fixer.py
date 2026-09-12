import re
from pathlib import Path

def _format_join_region(sql: str) -> str:
    start_match = re.search(r"(?im)^\s*FROM\b", sql)
    if not start_match:
        return sql
    prefix, region = sql[:start_match.start()], sql[start_match.start():]
    region = re.sub(r"(?i)\bSELECT\s*\*\s*FROM", "SELECT * FROM", region)
    region = re.sub(r"(?i)(<>|=)\s*\"\s*(?=\s*(?:AND|OR|LEFT|RIGHT|INNER|FULL|CROSS|$|;))", r"\1 ''", region)
    region = re.sub(r"(?i)\bFROM\s*\(", "FROM (", region)
    region = re.sub(r"(?i)\bJOIN\s*\(", "JOIN (", region)
    region = re.sub(r"(?i)\b(LEFT|RIGHT|INNER|FULL|CROSS)\s+JOIN", lambda match: match.group(1).upper() + " JOIN", region)
    region = re.sub(r"(?i)\s+ON\s+", "\n    ON ", region)
    region = re.sub(r"(?i)\s+AND\s+", "\n   AND ", region)
    region = re.sub(r"\s*\n\s*", "\n", region)
    region = re.sub(r"(?im)^\s*(LEFT|RIGHT|INNER|FULL|CROSS) JOIN", lambda match: "\n" + match.group(1) + " JOIN", region)
    region = re.sub(r"(?im)^\s*(FROM)\s+\(", r"FROM (", region)
    region = re.sub(r"\(\s*SELECT\s+", "(\n    SELECT ", region, flags=re.IGNORECASE)
    region = re.sub(r"\s+FROM\s+", "\n    FROM ", region, flags=re.IGNORECASE)
    region = re.sub(r"\s+WHERE\s+", "\n    WHERE ", region, flags=re.IGNORECASE)
    region = re.sub(r"\s*\)\s*(?!AND\b|OR\b|ON\b|WHERE\b|LEFT\b|RIGHT\b|INNER\b|FULL\b|CROSS\b)([A-Za-z_]\w*)", r"\n) \1", region, flags=re.IGNORECASE)
    region = re.sub(r"(?im)^\s*(ON|AND)\s+", lambda match: ("    " if match.group(1).upper() == "ON" else "   ") + match.group(1).upper() + " ", region)
    region = re.sub(r"(?i)(['\"])\s*((?:LEFT|RIGHT|INNER|FULL|CROSS)\s+JOIN)\b", r"\1\n\2", region)
    return prefix + region.strip()

def fix_sql_string(sql: str) -> tuple[str, list[str]]:
    fixes = []
    fixed = sql.replace("||", " || ")
    if fixed != sql: fixes.append("normalized concatenation operators")
    fixed, count = re.subn(r"\bNVL\s*\(", "COALESCE(", fixed, flags=re.I)
    if count: fixes.append("translated NVL to COALESCE")
    fixed, count = re.subn(r"(?im)^\s*,\s*(?=FROM\b)", "", fixed)
    if count: fixes.append("removed trailing comma before FROM")
    fixed, count = re.subn(r"(?im)^\s*FROM\s+DUAL\s*;?\s*$", "", fixed)
    if count: fixes.append("removed legacy FROM DUAL")
    fixed, count = re.subn(r"(?i)\b(TBD|TBC|PLACEHOLDER|XXX)\b", r"NULL /* TODO: \1 placeholder */", fixed)
    if count: fixes.append("marked unresolved placeholder tokens as TODO")
    fixed, count = re.subn(r"(?im)^\s*(--.*)?\b(as of today|populate from mapping note)\s*$", "-- TODO: unresolved prose: \\2", fixed)
    if count: fixes.append("marked unresolved prose as TODO")
    normalized = _format_join_region(fixed)
    if normalized != fixed:
        if re.search(r"(?i)\bSELECT\s*\*\s*FROM", fixed):
            fixes.append("normalized SELECT/FROM spacing")
        if re.search(r'(?i)(?:<>|=)\s*"', fixed):
            fixes.append("normalized empty-string comparisons")
        if re.search(r"(?i)\bJOIN\b", fixed):
            fixes.append("standardized JOIN formatting")
        fixed = normalized
    if fixed.count("(") != fixed.count(")"):
        fixed += "\n-- TODO: unbalanced parentheses require review\n"; fixes.append("flagged unbalanced parentheses")
    if fixed.strip() and not fixed.rstrip().endswith(";"):
        fixed = fixed.rstrip() + ";\n"
        fixes.append("added missing statement terminator")
    return fixed, list(dict.fromkeys(fixes))

def fix_sql_file(file_path: str, target_table: str = "", output_dir: str = "output"):
    path = Path(file_path); fixed, fixes = fix_sql_string(path.read_text(encoding="utf-8"))
    out = Path(output_dir) / "deterministic_fix" / f"{(target_table or path.stem).lower()}.sql"; out.parent.mkdir(parents=True, exist_ok=True); out.write_text(fixed, encoding="utf-8")
    return fixed, fixes, str(out)
