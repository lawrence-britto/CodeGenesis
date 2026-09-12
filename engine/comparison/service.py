from __future__ import annotations

import ast
import difflib
import json
import re
from typing import Any

import yaml


def _lines(baseline: str, tested: str) -> tuple[str, int, int]:
    diff = list(difflib.unified_diff(baseline.splitlines(True), tested.splitlines(True), fromfile="baseline", tofile="tested"))
    return "".join(diff), sum(line.startswith("+") and not line.startswith("+++") for line in diff), sum(line.startswith("-") and not line.startswith("---") for line in diff)


def _canonical_diff(baseline: str, tested: str) -> dict[str, Any]:
    baseline_lines = baseline.splitlines()
    tested_lines = tested.splitlines()
    matcher = difflib.SequenceMatcher(a=baseline_lines, b=tested_lines, autojunk=False)
    consolidated: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    change_blocks: list[dict[str, Any]] = []
    change_index = 0

    for tag, before_start, before_end, after_start, after_end in matcher.get_opcodes():
        before = baseline_lines[before_start:before_end]
        after = tested_lines[after_start:after_end]
        if tag == "equal":
            for offset, content in enumerate(before):
                line_number = before_start + offset + 1
                consolidated.append({"kind": "context", "line_number": line_number, "content": content})
                rows.append({"baseline": {"line_number": line_number, "content": content}, "tested": {"line_number": after_start + offset + 1, "content": content}, "change_type": "unchanged"})
            continue

        change_index += 1
        block = {"index": change_index, "baseline_start": before_start + 1, "baseline_end": before_end, "tested_start": after_start + 1, "tested_end": after_end, "change_type": "modified" if before and after else "removed" if before else "added"}
        change_blocks.append(block)
        pair_count = min(len(before), len(after))
        for offset in range(pair_count):
            baseline_line = {"line_number": before_start + offset + 1, "content": before[offset]}
            tested_line = {"line_number": after_start + offset + 1, "content": after[offset]}
            consolidated.extend([
                {"kind": "removed", "line_number": baseline_line["line_number"], "content": baseline_line["content"], "change_index": change_index},
                {"kind": "added", "line_number": tested_line["line_number"], "content": tested_line["content"], "change_index": change_index},
            ])
            rows.append({"baseline": baseline_line, "tested": tested_line, "change_type": "modified", "change_index": change_index})
        for offset, content in enumerate(before[pair_count:], pair_count):
            line = {"line_number": before_start + offset + 1, "content": content}
            consolidated.append({"kind": "removed", **line, "change_index": change_index})
            rows.append({"baseline": line, "tested": None, "change_type": "removed", "change_index": change_index})
        for offset, content in enumerate(after[pair_count:], pair_count):
            line = {"line_number": after_start + offset + 1, "content": content}
            consolidated.append({"kind": "added", **line, "change_index": change_index})
            rows.append({"baseline": None, "tested": line, "change_type": "added", "change_index": change_index})

    return {"consolidated": consolidated, "rows": rows, "change_blocks": change_blocks}


def _sql_structure(content: str) -> dict[str, list[str]]:
    def unique(pattern: str) -> list[str]:
        return sorted(dict.fromkeys(re.findall(pattern, content, re.I)))

    join_pattern = re.compile(
        r"\b((?:(?:LEFT|RIGHT|FULL|INNER|CROSS)\s+)?JOIN\s+[\w.$]+(?:\s+(?:AS\s+)?\w+)?\s+(?:ON\s+.*?|USING\s*\([^)]*\)))"
        r"(?=\b(?:(?:LEFT|RIGHT|FULL|INNER|CROSS)\s+)?JOIN\b|\bWHERE\b|\bGROUP\s+BY\b|\bHAVING\b|\bORDER\s+BY\b|\bLIMIT\b|;|$)",
        re.I | re.S,
    )
    joins = sorted(dict.fromkeys(re.sub(r"\s+", " ", match.group(1)).strip() for match in join_pattern.finditer(content)))
    return {
        "columns": unique(r"(?:SELECT|,)\s*([\w.]+)(?:\s+AS\s+\w+)?(?=\s*,|\s+FROM|\s*$)"),
        "tables": unique(r"\b(?:FROM|JOIN)\s+([\w.$]+)"),
        "joins": joins,
        "ctes": unique(r"\b([A-Za-z_]\w*)\s+AS\s*\("),
        "clauses": unique(r"\b(WHERE|GROUP BY|HAVING|ORDER BY|LIMIT|UNION(?:\s+ALL)?)\b"),
    }


def _python_structure(content: str) -> dict[str, list[str]]:
    try:
        tree = ast.parse(content)
    except (SyntaxError, IndentationError):
        return {"imports": [], "functions": [], "classes": [], "calls": []}
    imports = []
    functions = []
    classes = []
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.Call):
            calls.append(ast.unparse(node.func) if hasattr(ast, "unparse") else type(node.func).__name__)
    return {"imports": sorted(set(imports)), "functions": sorted(set(functions)), "classes": sorted(set(classes)), "calls": sorted(set(calls))}


def _yaml_structure(content: str) -> dict[str, list[str]]:
    try:
        value = yaml.safe_load(content)
    except yaml.YAMLError:
        return {"keys": [], "kinds": []}
    keys = []
    kinds = []
    def walk(item: Any, prefix: str = "") -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                keys.append(path)
                walk(child, path)
        elif isinstance(item, list):
            kinds.append(prefix or "list")
            for child in item:
                walk(child, prefix)
    walk(value)
    return {"keys": sorted(keys), "kinds": sorted(set(kinds))}


def _structure(language: str, content: str) -> dict[str, list[str]]:
    if language == "sql":
        return _sql_structure(content)
    if language == "python":
        return _python_structure(content)
    if language == "yaml":
        return _yaml_structure(content)
    if language == "shell":
        commands = re.findall(r"^\s*([A-Za-z][\w.-]*)\b", content, re.M)
        return {"commands": sorted(set(commands))}
    return {}


def _semantic_signature(language: str, content: str) -> str:
    if language == "python":
        try:
            return ast.dump(ast.parse(content), annotate_fields=True, include_attributes=False)
        except (SyntaxError, IndentationError):
            return content
    if language == "yaml":
        try:
            return json.dumps(yaml.safe_load(content), sort_keys=True, separators=(",", ":"))
        except yaml.YAMLError:
            return content
    if language == "sql":
        return re.sub(r"\s+", " ", re.sub(r";\s*$", "", content.strip())).casefold()
    return content


def compare_content(baseline: str, tested: str, language: str) -> dict[str, Any]:
    unified_diff, added, removed = _lines(baseline, tested)
    canonical = _canonical_diff(baseline, tested)
    before = _structure(language, baseline)
    after = _structure(language, tested)
    changes = []
    for key in sorted(set(before) | set(after)):
        added_items = sorted(set(after.get(key, [])) - set(before.get(key, [])))
        removed_items = sorted(set(before.get(key, [])) - set(after.get(key, [])))
        if added_items or removed_items:
            changes.append({"area": key, "added": added_items, "removed": removed_items})
    return {"unified_diff": unified_diff, "added_lines": added, "removed_lines": removed, "structure": after, "structural_changes": changes, "text_difference": bool(unified_diff), "semantic_difference": _semantic_signature(language, baseline) != _semantic_signature(language, tested), "diff_lines": canonical["consolidated"], "side_by_side": canonical["rows"], "change_blocks": canonical["change_blocks"]}
