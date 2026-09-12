import re
from typing import Any


_CONTROL_SEPARATORS = "\x02\x03\x1e\x1f\x00"


def _top_level_keyword(text: str, keyword: str, start: int = 0) -> int:
    depth = 0
    quote = False
    index = start
    pattern = re.compile(rf"\b{re.escape(keyword)}\b", re.IGNORECASE)
    while index < len(text):
        char = text[index]
        if char == "'":
            if quote and index + 1 < len(text) and text[index + 1] == "'":
                index += 2
                continue
            quote = not quote
        elif not quote:
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            elif depth == 0:
                match = pattern.match(text, index)
                if match:
                    return index
        index += 1
    return -1


def _split_top_level_csv(text: str) -> list[str]:
    result, start, depth, quote, index = [], 0, 0, False, 0
    while index < len(text):
        char = text[index]
        if char == "'":
            if quote and index + 1 < len(text) and text[index + 1] == "'":
                index += 2
                continue
            quote = not quote
        elif not quote:
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            elif char == "," and depth == 0:
                if text[start:index].strip():
                    result.append(text[start:index].strip())
                start = index + 1
        index += 1
    if text[start:].strip():
        result.append(text[start:].strip())
    return result


def parse_source_sql(sql_text: str) -> dict[str, Any]:
    text = str(sql_text or "").strip()
    if not text:
        raise ValueError("Source SQL is empty")
    match = re.search(r"\bSELECT\b", text, re.IGNORECASE)
    if not match:
        raise ValueError("Source SQL does not contain SELECT")
    payload = text[match.start():]
    separators = [payload.find(char) for char in _CONTROL_SEPARATORS if payload.find(char) >= 0]
    if separators:
        payload = payload[:min(separators)]
    payload = payload.strip().rstrip(";").strip()
    select_pos = _top_level_keyword(payload, "SELECT")
    from_pos = _top_level_keyword(payload, "FROM", select_pos + 6)
    if select_pos < 0 or from_pos <= select_pos:
        raise ValueError("Source SQL must be a top-level SELECT...FROM query")
    query_prefix = payload[:select_pos].strip()
    select_body = payload[select_pos + 6:from_pos]
    columns = _split_top_level_csv(select_body)
    alias_map: dict[str, str] = {}
    for expression in columns:
        alias_match = re.search(r"\bAS\s+([A-Za-z_]\w*)\s*$", expression, re.IGNORECASE)
        if alias_match:
            alias_map[alias_match.group(1).upper()] = expression
    return {
        "query_prefix": query_prefix,
        "select_columns": columns,
        "select_aliases": set(alias_map),
        "select_alias_map": alias_map,
        "join_text": payload[from_pos:].strip(),
    }
