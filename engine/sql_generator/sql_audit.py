from pathlib import Path
import re


def _without_comments(content: str) -> str:
    content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", "", content)


def _structural_checks(content: str) -> list[str]:
    clean = _without_comments(content)
    issues = []
    if len(re.findall(r"\bCASE\b", clean, re.IGNORECASE)) != len(re.findall(r"\bEND\b", clean, re.IGNORECASE)):
        issues.append("CASE/END keyword count mismatch")
    if clean.count("(") != clean.count(")"):
        issues.append("overall parenthesis count mismatch")
    if re.search(r",\s*\bFROM\b", clean, re.IGNORECASE):
        issues.append("trailing comma before FROM")
    if re.search(r"\b(?:AND|OR)\s*(?:FROM|WHERE|GROUP BY|ORDER BY|HAVING|UNION)\b", clean, re.IGNORECASE):
        issues.append("trailing AND/OR before a clause boundary")
    if not clean.rstrip().endswith(";"):
        issues.append("missing statement terminator")
    if re.search(r"\b(?:TBD|TBC|PLACEHOLDER|XXX)\b", clean, re.IGNORECASE):
        issues.append("unresolved placeholder token")
    return issues


_PATTERN_CHECKS = [
    (r"\bNVL\s*\(", "legacy NVL should become COALESCE", re.IGNORECASE),
    (r"\bFROM\s+DUAL\b", "legacy FROM DUAL should be removed", re.IGNORECASE),
    (r"\b(?:as of today|confirm with BA|mapping note)\b", "narrative mapping prose remains in SQL", re.IGNORECASE),
    (r"/\*\s*(?:TODO|FIXME)\b", "TODO/FIXME requires BA review", re.IGNORECASE),
]


def pattern_checks(content: str) -> list[str]:
    return [message for pattern, message, flags in _PATTERN_CHECKS if re.search(pattern, content, flags)]


def _line_checks(lines: list[str]) -> list[str]:
    issues = []
    if any(re.search(r"\b(?:AND|OR)\s*$", line, re.IGNORECASE) for line in lines):
        issues.append("line ends with a dangling AND/OR")
    return issues


def audit_sql(content: str) -> list[str]:
    """Audit SQL content without requiring a temporary file."""
    return _structural_checks(content) + pattern_checks(content) + _line_checks(content.splitlines())


def audit_metadata(content: str) -> dict[str, int | bool]:
    """Return lightweight metadata used by reports and RAG retrieval."""
    clean = _without_comments(content)
    return {
        "select_count": len(re.findall(r"\bSELECT\b", clean, re.IGNORECASE)),
        "join_count": len(re.findall(r"\bJOIN\b", clean, re.IGNORECASE)),
        "from_count": len(re.findall(r"\bFROM\b", clean, re.IGNORECASE)),
        "todo_count": len(re.findall(r"\bTODO\b", content, re.IGNORECASE)),
        "has_issues": bool(audit_sql(content)),
    }


def audit_file(path: Path) -> list[str]:
    content = path.read_text(encoding="utf-8")
    return audit_sql(content)


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default="output/deterministic_fix")
    args = parser.parse_args(argv)
    path = Path(args.path)
    files = [path] if path.is_file() else sorted(path.glob("*.sql"))
    issues = []
    for file in files:
        found = audit_file(file)
        for issue in found:
            print(f"{file}: {issue}")
        issues.extend(found)
    return 1 if issues else 0
