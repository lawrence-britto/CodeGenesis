from __future__ import annotations

import ast
import re
from typing import Any

from engine.universal_models import Finding


def analyze_risk(language: str, baseline: str, tested: str, structural_changes: list[dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    if language == "sql":
        for change in structural_changes:
            area = change.get("area")
            removed = change.get("removed", [])
            added = change.get("added", [])
            if area == "columns" and removed:
                findings.append(Finding("MEDIUM", "result-shape", "Potential risk: one or more selected columns were removed or changed.", "The tested query may return a different result shape or omit required data.", recommendation="Confirm every removed or modified column with the mapping and downstream consumers.", code="SQL_COLUMNS_CHANGED"))
            elif area == "tables" and removed:
                findings.append(Finding("HIGH", "data-source", "Potential risk: one or more source tables were removed or changed.", "The tested query may read from a different data source or omit records.", recommendation="Validate the source table and its required relationship before acceptance.", code="SQL_TABLES_CHANGED"))
            elif area == "clauses" and removed:
                findings.append(Finding("HIGH", "query-logic", "Potential risk: one or more SQL clauses were removed or changed.", "Filtering, grouping, ordering, or row limits may no longer match production behavior.", recommendation="Review every removed or modified clause and validate representative results.", code="SQL_CLAUSES_CHANGED"))
        if re.search(r"\bWHERE\b", baseline, re.I) and not re.search(r"\bWHERE\b", tested, re.I):
            findings.append(Finding("HIGH", "result-set", "Potential risk: the tested SQL removes the WHERE condition.", "The query may return substantially more records.", recommendation="Review the intended filtering behavior before acceptance.", code="SQL_WHERE_REMOVED"))
        if re.search(r"\bWHERE\b", tested, re.I) and not re.search(r"\bWHERE\b", baseline, re.I):
            findings.append(Finding("HIGH", "result-set", "Potential risk: the tested SQL adds the WHERE condition.", "The query may return fewer records than production.", recommendation="Review the intended filtering behavior before acceptance.", code="SQL_WHERE_ADDED"))
        if re.search(r"\bJOIN\b", baseline, re.I) and not re.search(r"\bJOIN\b", tested, re.I):
            findings.append(Finding("HIGH", "result-set", "Potential risk: a JOIN was removed.", "Rows may be duplicated, omitted, or sourced differently.", recommendation="Confirm the expected relationship and result cardinality.", code="SQL_JOIN_REMOVED"))
        if re.search(r"\bJOIN\b", tested, re.I) and not re.search(r"\bJOIN\b", baseline, re.I):
            findings.append(Finding("HIGH", "result-set", "Potential risk: a JOIN was added.", "Rows may be duplicated, omitted, or sourced differently.", recommendation="Confirm the expected relationship, join condition, and result cardinality.", code="SQL_JOIN_ADDED"))
        if any(change.get("area") == "joins" and change.get("added") and change.get("removed") for change in structural_changes):
            findings.append(Finding("HIGH", "result-set", "Potential risk: JOIN behavior changed.", "The tested query uses a different relationship or join condition.", recommendation="Review the complete JOIN condition and expected result cardinality.", code="SQL_JOIN_CHANGED"))
        if re.search(r"\bSELECT\s+\*", tested, re.I) and not re.search(r"\bSELECT\s+\*", baseline, re.I):
            findings.append(Finding("MEDIUM", "maintainability", "Potential risk: SELECT * was introduced.", "Schema changes may silently alter the result shape.", recommendation="Name the required columns explicitly.", code="SQL_SELECT_STAR"))
    elif language == "shell":
        for change in structural_changes:
            if change.get("area") == "commands" and change.get("removed"):
                findings.append(Finding("HIGH", "command-flow", "Potential risk: one or more shell commands were removed or changed.", "The tested script may skip required work or execute a different operational sequence.", recommendation="Review the complete command flow and validate side effects in a controlled environment.", code="SHELL_COMMANDS_CHANGED"))
        if re.search(r"\brm\s+-[rf]{1,2}\b", tested) and not re.search(r"\brm\s+-[rf]{1,2}\b", baseline):
            findings.append(Finding("CRITICAL", "destructive-command", "Potential risk: rm -rf was introduced.", "The command can recursively delete files.", recommendation="Verify the path and require explicit approval.", code="SHELL_RM_RF"))
        if re.search(r"\bsudo\b", tested) and not re.search(r"\bsudo\b", baseline):
            findings.append(Finding("HIGH", "privilege", "Potential risk: sudo usage was introduced.", "The script now requests elevated privileges.", recommendation="Review the exact command and least-privilege alternative.", code="SHELL_SUDO"))
    elif language == "python":
        for change in structural_changes:
            if change.get("area") in {"imports", "classes", "calls"} and change.get("removed"):
                findings.append(Finding("HIGH", "behavior", f"Potential risk: Python {change.get('area')} were removed or changed.", "The tested file may no longer initialize dependencies or perform required behavior.", recommendation="Review removed definitions and call sites, then run regression tests for affected workflows.", code=f"PYTHON_{change.get('area', 'structure').upper()}_CHANGED"))
        if "subprocess" in tested and "subprocess" not in baseline:
            findings.append(Finding("HIGH", "process", "Potential risk: subprocess usage was introduced.", "The tested file can start external processes.", recommendation="Review command construction, input handling, and allowed binaries.", code="PYTHON_SUBPROCESS"))
        if any(change.get("area") == "functions" and (change.get("added") or change.get("removed")) for change in structural_changes):
            findings.append(Finding("HIGH", "behavior", "Potential risk: Python functions were added or removed.", "Application behavior may have changed at function boundaries.", recommendation="Review each changed function and its callers before acceptance.", code="PYTHON_FUNCTION_CHANGED"))
        try:
            before = {node.name: ast.dump(node, include_attributes=False) for node in ast.walk(ast.parse(baseline)) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
            after = {node.name: ast.dump(node, include_attributes=False) for node in ast.walk(ast.parse(tested)) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
            if any(name in before and before[name] != after.get(name) for name in after):
                findings.append(Finding("HIGH", "behavior", "Potential risk: an existing Python function changed.", "The tested file changes executable application behavior.", recommendation="Review the changed function logic and its callers before acceptance.", code="PYTHON_FUNCTION_MODIFIED"))
        except (SyntaxError, IndentationError):
            pass
    elif language == "yaml":
        for change in structural_changes:
            if change.get("area") == "keys" and change.get("removed"):
                findings.append(Finding("HIGH", "configuration", "Potential risk: one or more configuration keys were removed or changed.", "Runtime behavior may fall back to defaults or omit required settings.", recommendation="Review each removed key and validate the deployed configuration.", code="YAML_KEYS_CHANGED"))
            if any("replicas" in item.lower() for item in change.get("added", [])):
                findings.append(Finding("MEDIUM", "capacity", "Potential risk: Kubernetes replica configuration changed.", "This may change resource consumption.", recommendation="Confirm capacity and autoscaling limits.", code="YAML_REPLICAS"))
    return findings


def overall_status(valid: bool, semantic_difference: bool, findings: list[Finding]) -> str:
    if not valid:
        return "BLOCKED"
    severities = {finding.severity for finding in findings}
    if "CRITICAL" in severities or "HIGH" in severities:
        return "HIGH RISK - REVIEW CHANGES"
    if semantic_difference:
        return "WARNING - REVIEW CHANGES"
    return "WARNING" if findings else "SAFE"
