from dataclasses import dataclass
from pathlib import Path
import re

@dataclass
class Action:
    alias: str
    table: str
    kind: str
    detail: str
    columns: list[str]
    changed: bool

_TABLE_RE = re.compile(
    r"\b(FROM|JOIN)\s+(?P<table>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)"
    r"(?:\s+(?:AS\s+)?(?P<alias>[A-Za-z_]\w*))?",
    re.IGNORECASE,
)
_SUBQUERY_RE = re.compile(
    r"\b(?P<clause>FROM|JOIN)\s*\(\s*SELECT\s+(?:\*\s+)?FROM\s+"
    r"(?P<table>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)(?P<body>.*?)\)\s*"
    r"(?:AS\s+)?(?P<alias>[A-Za-z_]\w*)",
    re.IGNORECASE | re.DOTALL,
)
_COLUMN_RE = re.compile(r"\b(?P<alias>[A-Za-z_]\w*)\s*\.\s*(?P<column>[A-Za-z_]\w*)\b")
_SQL_WORDS = {
    "FROM", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "FULL", "CROSS",
    "ON", "WHERE", "GROUP", "ORDER", "HAVING", "UNION", "LIMIT",
}

def _without_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", lambda match: " " * len(match.group(0)), sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", lambda match: " " * len(match.group(0)), sql)

def _entries(sql: str) -> list[tuple[re.Match[str], str]]:
    clean = _without_comments(sql)
    entries = []
    for match in _TABLE_RE.finditer(clean):
        alias = match.group("alias") or match.group("table").rsplit(".", 1)[-1]
        if alias.upper() in _SQL_WORDS:
            alias = ""
        entries.append((match, alias))
    return entries

def process_file(path: Path) -> tuple[str, list[Action]]:
    sql = path.read_text(encoding="utf-8")
    clean = _without_comments(sql)
    usages: dict[str, set[str]] = {}
    for match in _COLUMN_RE.finditer(clean):
        usages.setdefault(match.group("alias").upper(), set()).add(match.group("column"))

    subqueries = list(_SUBQUERY_RE.finditer(clean))
    if subqueries:
        actions: list[Action] = []
        replacements: list[tuple[int, int, str]] = []
        for match in subqueries:
            alias = match.group("alias")
            table = match.group("table")
            columns = sorted(usages.get(alias.upper(), set()))
            if not columns:
                actions.append(Action(alias, table, "skip", "No qualified column usage found; left unchanged", [], False))
                continue
            projection = ", ".join(columns)
            replacement = f"{match.group('clause')} (SELECT {projection} FROM {table}{match.group('body')}) {alias}"
            replacements.append((match.start(), match.end(), replacement))
            actions.append(Action(alias, table, "table-projection", "Projected only qualified columns used by the query", columns, True))
        if replacements:
            result = sql
            for start, end, replacement in reversed(replacements):
                result = result[:start] + replacement + result[end:]
            return result, actions
        return sql, actions

    entries = _entries(sql)
    if not entries:
        return sql, [Action("", "", "skip", "No simple FROM/JOIN table references found", [], False)]

    actions: list[Action] = []
    replacements: list[tuple[int, int, str]] = []
    for match, alias in entries:
        table = match.group("table")
        key = alias.upper() if alias else table.rsplit(".", 1)[-1].upper()
        columns = sorted(usages.get(key, set()))
        if not columns:
            actions.append(Action(alias, table, "skip", "No qualified column usage found; left unchanged", [], False))
            continue
        if not alias:
            actions.append(Action("", table, "skip", "Table has no explicit alias; left unchanged", columns, False))
            continue
        projection = ", ".join(columns)
        replacement = f"{match.group(1)} (SELECT {projection} FROM {table}) {alias}"
        replacements.append((match.start(), match.end(), replacement))
        actions.append(Action(alias, table, "table-projection", "Projected only qualified columns used by the query", columns, True))

    if not replacements:
        return sql, actions
    result = sql
    for start, end, replacement in reversed(replacements):
        result = result[:start] + replacement + result[end:]
    return result, actions

def prune_sql_file(path: str):
    file = Path(path)
    new_sql, actions = process_file(file)
    if any(action.changed for action in actions):
        file.write_text(new_sql, encoding="utf-8")
    return new_sql, actions
