from pathlib import Path
import re


def _strip_previous_annotations(text: str) -> str:
    lines = text.splitlines()
    return "\n".join(line for line in lines if "TODO: [JOIN-VALIDATOR]" not in line and "JOIN-VALIDATOR:" not in line)


def _distance_one(left: str, right: str) -> bool:
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) > len(right):
        left, right = right, left
    differences = 0
    index = 0
    for position in range(len(left)):
        if left[position] != right[index]:
            differences += 1
            if len(left) != len(right):
                index += 1
        index += 1
        if differences > 1:
            return False
    return differences + (len(right) - len(left)) <= 1


def validate_join_syntax(sql_text: str, config: dict | None = None, llm=None):
    text = _strip_previous_annotations(sql_text)
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if re.match(r"^\s*FROM\b", line, re.IGNORECASE)), None)
    if start is None:
        return text, [], []
    region = lines[start:]
    declared = {match.group(1).lower(): match.group(1) for match in re.finditer(r"\)\s*(?:AS\s+)?([A-Za-z_]\w*)", "\n".join(region), re.IGNORECASE)}
    declared.update({match.group(1).lower(): match.group(1) for match in re.finditer(r"\b(?:FROM|JOIN)\s+[\w.]+\s+(?:AS\s+)?([A-Za-z_]\w*)", "\n".join(region), re.IGNORECASE)})
    issues, fixes = [], []
    join_starts = [index for index, line in enumerate(region) if re.search(r"\b(?:LEFT|RIGHT|FULL|INNER|CROSS)?\s*JOIN\b", line, re.IGNORECASE)]
    for position, join_index in enumerate(join_starts):
        block = "\n".join(region[join_index:join_starts[position + 1] if position + 1 < len(join_starts) else len(region)])
        if not re.search(r"\bON\b", block, re.IGNORECASE) and not re.search(r"\bCROSS\s+JOIN\b", block, re.IGNORECASE):
            issues.append(f"JOIN missing ON condition: {region[join_index].strip()}")
        code = re.sub(r"--.*$", "", block, flags=re.MULTILINE)
        if code.count("(") != code.count(")"):
            issues.append(f"JOIN block has unbalanced parentheses: {region[join_index].strip()}")
    last = len(region) - 1
    while last >= 0 and (not region[last].strip() or region[last].lstrip().startswith("--")):
        last -= 1
    if last >= 0 and re.search(r"(?:AND|OR)\s*$", re.sub(r"--.*$", "", region[last], flags=re.IGNORECASE)):
        issues.append("JOIN block has a dangling AND/OR")
    for match in list(re.finditer(r"\b([A-Za-z_]\w*)\s*\.\s*([A-Za-z_]\w*)", "\n".join(region))):
        token = match.group(1)
        if token.lower() in declared:
            continue
        candidates = [value for key, value in declared.items() if _distance_one(token.lower(), key)]
        if len(candidates) == 1:
            replacement = candidates[0]
            joined = "\n".join(lines).replace(token + ".", replacement + ".", 1)
            lines = joined.splitlines()
            fixes.append(f"Corrected alias {token} to {replacement}")
        elif token.upper() not in {"TRIM", "CAST", "CASE", "WHEN", "THEN", "ELSE", "END"}:
            issues.append(f"Undeclared join alias: {token}")
    result = "\n".join(lines)
    if issues:
        result += "\n" + "\n".join(f"-- TODO: [JOIN-VALIDATOR] {issue}" for issue in dict.fromkeys(issues))
    return result, list(dict.fromkeys(issues)), fixes


def validate_join_syntax_file(path: str, config: dict | None = None, llm=None):
    file = Path(path)
    text, issues, fixes = validate_join_syntax(file.read_text(encoding="utf-8"), config, llm)
    file.write_text(text, encoding="utf-8")
    return text, issues, fixes
