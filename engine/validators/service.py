from __future__ import annotations

import ast
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from engine.universal_models import Finding, ValidationResult

LANGUAGES = {"sql", "python", "shell", "yaml"}
EXTENSIONS = {".sql": "sql", ".py": "python", ".sh": "shell", ".yaml": "yaml", ".yml": "yaml"}
DISPLAY_NAMES = {"sql": "SQL", "python": "Python", "shell": "Shell", "yaml": "YAML"}


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError("while constructing a mapping", node.start_mark, f"duplicate key {key!r}", key_node.start_mark)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def detect_language(filename: str = "", content: str = "", override: str | None = None) -> dict[str, str]:
    if override and override.lower() in LANGUAGES:
        return {"language": override.lower(), "confidence": "Manual", "note": "Language selected by the user."}
    suffix_language = EXTENSIONS.get(Path(filename or "").suffix.lower())
    sample = content[:12000]
    scores = {language: 0 for language in LANGUAGES}
    if suffix_language:
        scores[suffix_language] += 3
    if re.search(r"\b(SELECT|INSERT\s+INTO|UPDATE\s+\w+\s+SET|CREATE\s+TABLE|WITH\s+\w+\s+AS)\b", sample, re.I):
        scores["sql"] += 3
    if re.search(r"(^|\n)\s*(from\s+\w+\s+import|import\s+\w+|def\s+\w+\s*\(|class\s+\w+\s*[:(])", sample):
        scores["python"] += 3
    if re.search(r"(^|\n)\s*(#!/.*\b(?:ba)?sh\b|if\s+\[|for\s+\w+\s+in\s+|case\s+.+\s+in|\$\{?\w+)", sample):
        scores["shell"] += 3
    try:
        parsed = yaml.safe_load(sample)
        if isinstance(parsed, (dict, list)) and (":" in sample or sample.lstrip().startswith("- ")):
            scores["yaml"] += 2
    except yaml.YAMLError:
        pass
    language = max(scores, key=scores.get) if max(scores.values()) else (suffix_language or "unknown")
    if language not in LANGUAGES:
        return {"language": "unknown", "confidence": "Low", "note": "The file type could not be determined."}
    score = scores[language]
    confidence = "High" if score >= 5 else "Medium" if score >= 3 else "Low"
    note = ""
    if language != "unknown" and suffix_language != language:
        note = f"This file appears to contain {DISPLAY_NAMES[language]} but has a {Path(filename).suffix or '.txt'} extension."
    return {"language": language, "confidence": confidence, "note": note}


def _finding(severity: str, category: str, message: str, **kwargs: Any) -> Finding:
    return Finding(severity=severity, category=category, message=message, **kwargs)


def _validate_sql(content: str) -> ValidationResult:
    errors: list[Finding] = []
    warnings: list[Finding] = []
    if content.count("(") != content.count(")"):
        errors.append(_finding("ERROR", "syntax", "Unbalanced parentheses.", code="SQL_PARENTHESIS", recommendation="Close every opened parenthesis."))
    if content.count("'") % 2:
        errors.append(_finding("ERROR", "syntax", "Unterminated single-quoted string.", code="SQL_QUOTE"))
    statements = [part.strip() for part in content.split(";") if part.strip()]
    if not statements:
        errors.append(_finding("ERROR", "syntax", "The SQL file contains no statement.", code="SQL_EMPTY"))
    for statement in statements:
        if re.match(r"^(SELECT|WITH)\b", statement, re.I) and not re.search(r"\bFROM\b", statement, re.I):
            errors.append(_finding("ERROR", "syntax", "SELECT statement has no FROM clause.", code="SQL_SELECT_FROM"))
        if re.search(r"\bJOIN\b(?![\s\S]*\bON\b|[\s\S]*\bUSING\b)", statement, re.I):
            errors.append(_finding("ERROR", "syntax", "JOIN is missing an ON or USING condition.", code="SQL_JOIN_CONDITION"))
        if re.search(r"\b(SELECT|INSERT|UPDATE|DELETE)\s*$", statement, re.I):
            errors.append(_finding("ERROR", "syntax", "SQL statement is incomplete.", code="SQL_INCOMPLETE"))
    if re.search(r"\bSELECT\s+\*", content, re.I):
        warnings.append(_finding("MEDIUM", "maintainability", "SELECT * is present.", code="SQL_SELECT_STAR", recommendation="Name the required columns explicitly."))
    return ValidationResult(not errors, "sql", errors, warnings, parser="deterministic-sql")


def _validate_python(content: str) -> ValidationResult:
    try:
        tree = ast.parse(content)
    except (SyntaxError, IndentationError) as error:
        return ValidationResult(False, "python", [_finding("ERROR", "syntax", error.msg, line=error.lineno, column=error.offset, code="PYTHON_SYNTAX")], parser="ast")
    warnings: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"exec", "eval"}:
            warnings.append(_finding("HIGH", "dangerous-operation", f"{node.func.id}() usage detected.", line=node.lineno, code="PYTHON_DYNAMIC_EXEC", recommendation="Avoid dynamic code execution for untrusted input."))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "Popen":
            warnings.append(_finding("HIGH", "process", "subprocess process creation detected.", line=node.lineno, code="PYTHON_SUBPROCESS", recommendation="Review command construction and input handling."))
    return ValidationResult(True, "python", warnings=warnings, parser="ast")


def _validate_shell(content: str) -> ValidationResult:
    errors: list[Finding] = []
    warnings: list[Finding] = []
    if shutil.which("bash"):
        process = subprocess.run(["bash", "-n"], input=content, text=True, capture_output=True, check=False)
        if process.returncode:
            match = re.search(r": line (\d+): (.*)", process.stderr)
            errors.append(_finding("ERROR", "syntax", (match.group(2) if match else process.stderr.strip()) or "Shell syntax is invalid.", line=int(match.group(1)) if match else None, code="SHELL_SYNTAX"))
    else:
        for token, message in (("if", "missing fi"), ("for", "missing done"), ("case", "missing esac")):
            if len(re.findall(rf"\b{token}\b", content)) > len(re.findall(rf"\b(?:fi|done|esac)\b", content)):
                errors.append(_finding("ERROR", "syntax", message, code="SHELL_STRUCTURE"))
    if re.search(r"\brm\s+-[rf]{1,2}\b", content):
        warnings.append(_finding("CRITICAL", "destructive-command", "rm -rf detected.", code="SHELL_RM_RF", recommendation="Verify the target path and require an explicit approval."))
    if re.search(r"\bsudo\b", content):
        warnings.append(_finding("HIGH", "privilege", "sudo command detected.", code="SHELL_SUDO"))
    if re.search(r"\bcurl\b[^\n|]*\|\s*(ba)?sh\b", content):
        warnings.append(_finding("HIGH", "remote-execution", "Remote content is piped directly to a shell.", code="SHELL_CURL_PIPE"))
    return ValidationResult(not errors, "shell", errors, warnings, parser="bash -n" if shutil.which("bash") else "deterministic-shell")


def _validate_yaml(content: str) -> ValidationResult:
    try:
        yaml.load(content, Loader=UniqueKeyLoader)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        return ValidationResult(False, "yaml", [_finding("ERROR", "syntax", getattr(error, "problem", str(error)), line=(mark.line + 1 if mark else None), column=(mark.column + 1 if mark else None), code="YAML_SYNTAX")], parser="yaml")
    return ValidationResult(True, "yaml", parser="yaml")


def validate_content(content: str, language: str) -> ValidationResult:
    language = language.lower()
    if language == "sql":
        return _validate_sql(content)
    if language == "python":
        return _validate_python(content)
    if language == "shell":
        return _validate_shell(content)
    if language == "yaml":
        return _validate_yaml(content)
    return ValidationResult(False, language, [_finding("ERROR", "unsupported", f"Unsupported file type: {language}.", code="UNSUPPORTED_TYPE")], status="UNSUPPORTED", analysis_available=False)
