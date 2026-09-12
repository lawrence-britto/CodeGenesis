from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import re

from .source_sql_parser import parse_source_sql


class ReportGenerator:
    def __init__(self, config: dict):
        self.config = config or {}

    @staticmethod
    def _table(rows):
        if not rows:
            return "<p class='empty'>No data available.</p>"
        return "<table><thead><tr>" + "".join(f"<th>{escape(str(column))}</th>" for column in rows[0]) + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in row) + "</tr>" for row in rows[1:]) + "</tbody></table>"

    @staticmethod
    def _list(values):
        return "<ul>" + "".join(f"<li>{escape(str(value))}</li>" for value in (values or [])) + "</ul>" if values else "<p class='empty'>None identified.</p>"

    @staticmethod
    def _source_objects(sql):
        pattern = re.compile(r"\b(?:FROM|JOIN)\s+(?:\(\s*SELECT.*?\bFROM\s+)?([A-Za-z_][\w.]*)\)?\s*(?:AS\s+)?([A-Za-z_]\w*)?", re.IGNORECASE | re.DOTALL)
        objects = []
        for match in pattern.finditer(sql):
            name, alias = match.group(1), match.group(2) or match.group(1).rsplit(".", 1)[-1]
            if alias.upper() in {"ON", "WHERE", "LEFT", "RIGHT", "INNER", "FULL", "CROSS", "JOIN"}:
                alias = name.rsplit(".", 1)[-1]
            if not any(item["object"] == name and item["alias"] == alias for item in objects):
                objects.append({"object": name, "alias": alias})
        return objects

    @staticmethod
    def _sql_analysis(sql, result):
        select_body = sql.split("FROM", 1)[0] if re.search(r"\bFROM\b", sql, re.IGNORECASE) else sql
        expressions = [item.strip() for item in re.split(r",\s*(?![^()]*\))", select_body.split("SELECT", 1)[-1], flags=re.IGNORECASE) if item.strip()]
        aliases = [match.group(1).upper() for expression in expressions if (match := re.search(r"\bAS\s+([A-Za-z_]\w*)\s*$", expression, re.IGNORECASE))]
        functions = sorted({match.group(1).upper() for match in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", sql)})
        duplicate_aliases = sorted({alias for alias in aliases if aliases.count(alias) > 1})
        normalized = [re.sub(r"\s+", "", expression).upper() for expression in expressions]
        duplicate_expressions = sorted({expression for expression in normalized if normalized.count(expression) > 1})
        joins = []
        join_pattern = re.compile(r"(?is)(?P<type>LEFT|RIGHT|FULL|INNER|CROSS)?\s*JOIN\s+(?P<table>.*?)(?:\s+ON\s+(?P<condition>.*?))(?=(?:\s+(?:LEFT|RIGHT|FULL|INNER|CROSS)?\s*JOIN\b|\s+WHERE\b|\s*;|$))")
        for match in join_pattern.finditer(sql):
            condition = re.sub(r"\s+", " ", match.group("condition")).strip()
            sides = re.search(r"([\w]+)\.([\w]+)\s*=\s*([\w]+)\.([\w]+)", condition)
            table_text = match.group("table").strip()
            right_table = re.findall(r"\bFROM\s+([A-Za-z_]\w*)", table_text, re.IGNORECASE)[-1] if re.search(r"\bFROM\s+", table_text, re.IGNORECASE) else table_text.split()[0]
            joins.append({"left_table": sides.group(1) if sides else "", "left_column": sides.group(2) if sides else "", "join_type": f"{(match.group('type') or '').upper()} JOIN".strip(), "right_table": sides.group(3) if sides else right_table, "right_column": sides.group(4) if sides else "", "condition": condition, "functions": sorted({name.upper() for name in re.findall(r"\b(TRIM|CAST|UPPER|LOWER)\s*\(", condition, re.IGNORECASE)}), "status": "PASS" if condition else "WARNING"})
        return {"select_columns": len(expressions), "direct_mappings": len(result.get("direct_mappings", [])), "derived_columns": len(result.get("dpr_default", [])) + len(result.get("dpr_transform", [])), "expressions": expressions, "functions": functions, "duplicate_expressions": duplicate_expressions, "duplicate_aliases": duplicate_aliases, "source_tables": len(ReportGenerator._source_objects(sql)), "subqueries": len(re.findall(r"\(\s*SELECT\b", sql, re.IGNORECASE)), "aliases": [item["alias"] for item in ReportGenerator._source_objects(sql)], "joins": joins, "filters": len(re.findall(r"\bWHERE\b|\bAND\b", sql, re.IGNORECASE))}

    @staticmethod
    def _mapping_rows(result):
        rows = result.get("mapping_rows", [])
        output = []
        for row in rows:
            source = str(row.get("Source Object Name", "")).strip()
            source_column = str(row.get("Source Attribute Name", "")).strip()
            target = str(row.get("Target Object Name", "")).strip()
            target_column = str(row.get("Target Attribute Name", "")).strip()
            rule = str(row.get("Data Processing Rule", row.get("DPR", ""))).strip()
            output.append({"map_group": str(row.get("Map Group ID", result.get("map_group_code", ""))).strip(), "source": source, "source_column": source_column, "target": target, "target_column": target_column, "transformation": rule or "Direct", "join_dependency": "Yes" if source and source in str(result.get("join_text", "")) else "No", "status": "PASS" if source and source_column and target and target_column else "REVIEW"})
        return output

    @staticmethod
    def _normalized_sql(value):
        return re.sub(r"\s+", " ", str(value or "")).strip().upper()

    @staticmethod
    def _join_alias(join):
        match = re.search(r"\)\s*(?:AS\s+)?([A-Za-z_]\w*)\s+ON\b", join, re.IGNORECASE)
        if not match:
            match = re.search(r"\bJOIN\s+([A-Za-z_]\w*)\s+(?:AS\s+)?([A-Za-z_]\w*)\s+ON\b", join, re.IGNORECASE)
        return next((value for value in match.groups() if value), "").upper() if match else ""

    @classmethod
    def _join_changes(cls, source_join_text, generated_join_text):
        def split_joins(text):
            starts = [match.start() for match in re.finditer(r"(?i)(?:LEFT|RIGHT|FULL|INNER|CROSS)?\s*JOIN\b", text or "")]
            joins = []
            for index, start in enumerate(starts):
                depth, quote, end = 0, False, len(text)
                cursor = start
                while cursor < len(text):
                    char = text[cursor]
                    if char == "'":
                        if quote and cursor + 1 < len(text) and text[cursor + 1] == "'":
                            cursor += 2
                            continue
                        quote = not quote
                    elif not quote:
                        if char == "(":
                            depth += 1
                        elif char == ")":
                            depth = max(0, depth - 1)
                        elif depth == 0 and cursor > start and (index + 1 < len(starts) and cursor >= starts[index + 1] or re.match(r"(?is)\s+(?:WHERE|GROUP\s+BY|ORDER\s+BY)\b", text[cursor:])):
                            end = cursor
                            break
                    cursor += 1
                joins.append(text[start:end].strip())
            return joins

        source_joins = split_joins(source_join_text)
        generated_joins = split_joins(generated_join_text)
        generated_by_alias = {cls._join_alias(join): join for join in generated_joins if cls._join_alias(join)}
        changes, matched = [], set()
        for source_join in source_joins:
            alias = cls._join_alias(source_join)
            generated_join = generated_by_alias.get(alias) if alias else None
            if generated_join is None:
                status, generated = "REMOVED", ""
            else:
                matched.add(id(generated_join))
                status = "UNCHANGED" if cls._normalized_sql(source_join) == cls._normalized_sql(generated_join) else "CHANGED"
                generated = generated_join
            changes.append({"change_type": status, "area": "JOIN", "identifier": alias or "source join", "source_sql": source_join, "generated_sql": generated, "details": "Present in existing source SQL; absent or altered in generated SQL" if status != "UNCHANGED" else "Preserved from existing source SQL"})
        for generated_join in generated_joins:
            if id(generated_join) not in matched and not any(cls._join_alias(item) == cls._join_alias(generated_join) for item in source_joins):
                changes.append({"change_type": "ADDED", "area": "JOIN", "identifier": cls._join_alias(generated_join) or "generated join", "source_sql": "", "generated_sql": generated_join, "details": "Added from the mapping sheet"})
        return changes

    @classmethod
    def _source_sql_changes(cls, source_sql, generated_sql):
        if not source_sql:
            return []
        source_info, generated_info = parse_source_sql(source_sql), parse_source_sql(generated_sql)
        changes = []
        source_aliases, generated_aliases = source_info.get("select_alias_map", {}), generated_info.get("select_alias_map", {})
        for alias, expression in source_aliases.items():
            generated = generated_aliases.get(alias, "")
            if not generated:
                status, details = "REMOVED", "Existing source expression is not present in generated SQL"
            elif cls._normalized_sql(expression) == cls._normalized_sql(generated):
                status, details = "UNCHANGED", "Existing source expression is preserved"
            else:
                status, details = "CHANGED", "Generated expression differs from existing source SQL"
            changes.append({"change_type": status, "area": "SELECT", "identifier": alias, "source_sql": expression, "generated_sql": generated, "details": details})
        for alias, expression in generated_aliases.items():
            if alias not in source_aliases:
                changes.append({"change_type": "ADDED", "area": "SELECT", "identifier": alias, "source_sql": "", "generated_sql": expression, "details": "Added from the mapping sheet"})
        changes.extend(cls._join_changes(source_info.get("join_text", ""), generated_info.get("join_text", "")))
        return changes

    def build_report_data(self, result: dict, fixed_sql_path: str = "", applied_fixes=None, param_changes=None, prune_actions=None, advisory=None, context=None):
        context, advisory = context or {}, advisory or {}
        sql = Path(fixed_sql_path).read_text(encoding="utf-8") if fixed_sql_path and Path(fixed_sql_path).exists() else result.get("sql", "")
        warnings = list(dict.fromkeys(context.get("warnings", result.get("warnings", []))))
        todos = list(dict.fromkeys(context.get("todos", result.get("todos", [])) or [line.strip() for line in sql.splitlines() if re.search(r"\bTODO\b", line, re.IGNORECASE)]))
        errors = list(context.get("errors", []))
        analysis, source_objects, mapping_rows = self._sql_analysis(sql, result), self._source_objects(sql), self._mapping_rows(result)
        target_columns = len({row["target_column"] for row in mapping_rows if row["target_column"]}) or len(result.get("select_columns", []))
        fixes = [{"id": index, "issue": str(fix), "action": str(fix), "location": "Generated SQL", "impact": "Deterministic SQL correction", "status": "FIXED", "rule": "SQL syntax fixer"} for index, fix in enumerate(applied_fixes or [], 1)]
        for fix in context.get("join_fixes", []):
            fixes.append({"id": len(fixes) + 1, "issue": str(fix), "action": str(fix), "location": "JOIN clause", "impact": "Join structure correction", "status": "FIXED", "rule": "Join validator"})
        validation_status = "FAILED" if errors else ("WARNING" if warnings or todos else "PASSED")
        rag_rules = advisory.get("rules", []) or []
        rag_status = "DISABLED" if not self.config.get("rag", {}).get("enabled", True) else "COMPLETED"
        llm_error = advisory.get("error", "")
        findings = [{"severity": "ERROR" if finding in errors else "WARNING", "category": "SQL validation", "finding": finding, "evidence": finding, "recommendation": "Resolve before release"} for finding in errors + warnings]
        for fix in fixes:
            issue = fix["issue"]
            if "terminator" in issue.lower():
                finding = "Missing statement terminator"
                evidence = "Original SQL did not end with a statement terminator"
                recommendation = "Added the statement terminator to the deterministic SQL output"
            else:
                finding = issue
                evidence = f"Generated SQL contained a deterministic formatting defect: {issue}"
                recommendation = f"Applied {issue.lower()} to the deterministic SQL output"
            findings.append({"severity": "INFO", "category": "SQL syntax", "finding": finding, "evidence": evidence, "recommendation": recommendation})
        llm_explanation = advisory.get("explanation") or ("LLM diagnostic completed. No unresolved deterministic issues required explanation. Proceed to the testing phase by generating sample synthetic data using the Test Data Forge." if not errors and not warnings and not todos else "No diagnostic explanation was returned.")
        source_changes = self._source_sql_changes(Path(context["source_sql_path"]).read_text(encoding="utf-8") if context.get("source_sql_path") and Path(context["source_sql_path"]).exists() else "", sql)
        data = {"summary": {"overall_status": "FAILED" if errors else ("WARNING" if warnings or todos else "SUCCESS"), "sql_generation_status": "FAILED" if errors else "SUCCESS", "validation_status": validation_status, "mapping_status": context.get("mapping_status", "PASSED" if all(row["status"] == "PASS" for row in mapping_rows) else "WARNING"), "source_tables": len(source_objects), "target_columns": target_columns, "generated_columns": len(result.get("select_columns", [])), "joins": len(analysis["joins"]), "transformations": len(result.get("dpr_transform", [])), "deterministic_fixes": len(fixes), "warnings": len(warnings), "todos": len(todos), "unresolved_issues": len(errors) + len(warnings) + len(todos), "rag_status": rag_status, "llm_diagnostic_status": "FAILED" if llm_error else "COMPLETED"},
        "inputs": {"mapping_workbook": Path(context.get("excel_path", "")).name or "Unknown", "mapping_sheet": "Source to Target", "source_sql_file": Path(context.get("source_sql_path", "")).name if context.get("source_sql_path") else "Not supplied", "mapping_rows": result.get("mapping_row_count", len(mapping_rows)), "valid_mapping_rows": sum(row["status"] == "PASS" for row in mapping_rows), "rejected_mapping_rows": sum(row["status"] != "PASS" for row in mapping_rows), "source_objects": sorted({item["object"] for item in source_objects}), "target_objects": sorted({row["target"] for row in mapping_rows if row["target"]}) or [result.get("target_table", "")], "processing_timestamp": datetime.now(timezone.utc).isoformat(), "configuration_profile": context.get("profile", "default")},
        "mapping_analysis": mapping_rows,
        "source_object_analysis": [{"object": item["object"], "alias": item["alias"], "required_columns": [], "select": "Yes", "join": "Yes" if re.search(rf"\b{re.escape(item['alias'])}\.", sql, re.IGNORECASE) else "No", "where": "Yes" if re.search(r"\bWHERE\b", sql, re.IGNORECASE) else "No", "transformation": "Yes" if re.search(rf"\b(?:TRIM|CAST|UPPER|LOWER)\s*\([^)]*\b{re.escape(item['alias'])}\.", sql, re.IGNORECASE) else "No", "filter_conditions": "Detected in SQL" if re.search(r"\bWHERE\b", sql, re.IGNORECASE) else "None", "join_participation": "Joined" if re.search(rf"\bJOIN\b[^\n]*\b{re.escape(item['alias'])}\b", sql, re.IGNORECASE) else "Base source", "column_pruning": "See pruning actions"} for item in source_objects],
        "generated_sql": sql, "sql_metadata": {"sql_type": "SELECT", "target_object": result.get("target_table", ""), "select_columns": len(result.get("select_columns", [])), "source_tables": len(source_objects), "joins": len(analysis["joins"]), "where_filters": analysis["filters"], "transformations": len(result.get("dpr_transform", [])), "validation": validation_status}, "sql_analysis": analysis,
        "filters": [{"table": "", "column": "", "operator": "", "value": condition, "purpose": "SQL filter", "status": "PASS"} for condition in re.findall(r"(?i)([A-Za-z_]\w*\.[A-Za-z_]\w*\s*(?:=|<>|<=|>=|<|>)\s*'[^']*'|[A-Za-z_]\w*\.[A-Za-z_]\w*\s*(?:=|<>|<=|>=|<|>)\s*\w+)", sql)],
        "transformations": [{"target_column": item.get("target_attr", ""), "source_column": "", "transformation": item.get("process_type", ""), "generated_expression": next((expression for expression in result.get("dpr_transform", []) if re.search(rf"\b{re.escape(item.get('target_attr', ''))}\s*$", expression, re.IGNORECASE)), ""), "status": "PASS"} for item in result.get("dpr_details", [])],
        "deterministic_fixes": fixes, "deterministic_findings": findings, "todos": [{"id": f"TODO-{index:03d}", "category": "BA review", "description": todo, "source": "Generated SQL", "impact": "Requires deterministic clarification", "required_action": "Confirm with BA or developer", "owner": "BA"} for index, todo in enumerate(todos, 1)], "validation": [{"rule": "SQL syntax structure", "result": validation_status, "details": "; ".join(errors + warnings) or "Valid deterministic SQL structure"}, {"rule": "Unresolved TODOs", "result": "FAIL" if todos else "PASS", "details": f"{len(todos)} TODO(s)" if todos else "None"}],
        "rag_advisory": {"rules": [{"name": rule.get("title", "Untitled rule")} for rule in rag_rules]}, "llm_diagnostic": {"model": self.config.get("llm", {}).get("model", "Unknown"), "status": "FAILED" if llm_error else "COMPLETED", "prompt_purpose": "Explain deterministic findings and recommend corrective action", "issues_explained": warnings + todos, "explanation": llm_explanation, "recommendations": llm_explanation, "authority": "NONE", "error": llm_error},
        "traceability": [{**row, "sql_expression": next((expression for expression in result.get("select_columns", []) if re.search(rf"\b{re.escape(row['target_column'])}\s*$", expression, re.IGNORECASE)), ""), "sql_location": "SELECT"} for row in mapping_rows], "source_sql_changes": source_changes, "final_status": {"sql_generation": "FAILED" if errors else ("SUCCESS WITH WARNINGS" if warnings or todos else "SUCCESS"), "deterministic_validation": validation_status, "ba_review_required": bool(warnings or todos), "reason": f"{len(todos)} unresolved TODO(s); {len(warnings)} warning(s)" if warnings or todos else "No unresolved deterministic issues."}, "prune_actions": [str(action) for action in (prune_actions or []) if getattr(action, "changed", False)], "errors": errors}
        if not llm_error:
            data["llm_diagnostic"].pop("error", None)
        return data

    def generate_report(self, result: dict, fixed_sql_path: str = "", applied_fixes=None, param_changes=None, prune_actions=None, advisory=None, context=None) -> str:
        data = self.build_report_data(result, fixed_sql_path, applied_fixes, param_changes, prune_actions, advisory, context)
        return self._render_validator_style(data).replace("OPERATIONS / MAPPING VALIDATOR", "OPERATIONS / SQL GENERATOR").replace("<h1>Mapping Validation Report</h1>", "<h1>SQL Generation Report</h1>")
        def rows(mapping, keys): return [[mapping[key] for key in keys] for mapping in mapping]
        summary_rows = [[key.replace("_", " ").title(), value] for key, value in data["summary"].items()]
        sections = ["<h1>SQL Generation &amp; Validation Report</h1><h2>1. Executive Summary</h2>" + self._table([["Metric", "Result"], *summary_rows]), "<h2>2. Input Summary</h2>" + self._table([["Input", "Value"], *[[key.replace("_", " ").title(), value] for key, value in data["inputs"].items()]]), "<h2>3. Mapping Analysis</h2>" + self._table([["Map Group", "Source", "Source Column", "Target", "Target Column", "Transformation", "Join Dependency", "Status"], *rows(data["mapping_analysis"], ("map_group", "source", "source_column", "target", "target_column", "transformation", "join_dependency", "status"))]), "<h2>4. Source Object Analysis</h2>" + self._table([["Source Object", "Alias", "SELECT", "JOIN", "WHERE", "Transformation", "Filters", "Join Participation", "Pruning"], *rows(data["source_object_analysis"], ("object", "alias", "select", "join", "where", "transformation", "filter_conditions", "join_participation", "column_pruning"))])]
        metadata = "<p>" + " | ".join(f"<strong>{escape(str(key).replace('_', ' ').title())}:</strong> {escape(str(value))}" for key, value in data["sql_metadata"].items()) + "</p>"
        sections += ["<h2>5. Generated SQL</h2>" + metadata + f"<pre class='sql'>{escape(data['generated_sql'])}</pre>", "<h2>6. Deterministic Fixes</h2>" + self._table([["#", "Issue Detected", "Action Taken", "Location", "Impact", "Status"], *rows(data["deterministic_fixes"], ("id", "issue", "action", "location", "impact", "status"))]), "<h2>7. Deterministic Findings</h2>" + self._table([["Severity", "Category", "Finding", "Evidence", "Recommendation"], *rows(data["deterministic_findings"], ("severity", "category", "finding", "evidence", "recommendation"))]), "<h2>8. TODO / BA Review</h2>" + (self._table([["TODO ID", "Category", "Description", "Source", "Impact", "Required Action", "Owner"], *rows(data["todos"], ("id", "category", "description", "source", "impact", "required_action", "owner"))]) if data["todos"] else "<p>No unresolved TODOs identified.</p>"), "<h2>9. SQL Validation Result</h2>" + self._table([["Validation Rule", "Result", "Details"], *[[item["rule"], item["result"], item["details"]] for item in data["validation"]]])]
        rag = data["rag_advisory"]
        llm_rows = [["Field", "Value"], ["Model", data["llm_diagnostic"]["model"]], ["Diagnostic Status", data["llm_diagnostic"]["status"]], ["Prompt Purpose", data["llm_diagnostic"]["prompt_purpose"]], ["Issues Explained", json.dumps(data["llm_diagnostic"]["issues_explained"])], ["Authority", data["llm_diagnostic"]["authority"]], ["Explanation & Recommendation", data["llm_diagnostic"]["explanation"]]]
        if data["llm_diagnostic"].get("error"):
            llm_rows.append(["Error", data["llm_diagnostic"]["error"]])
        sections += ["<h2>10. RAG Advisory</h2>" + self._table([["Rule"], *[[item["name"]] for item in rag["rules"]]]), "<h2>11. LLM Diagnostic</h2>" + self._table(llm_rows)]
        final = data["final_status"]
        sections += ["<h2>12. Traceability</h2>" + self._table([["Map Group", "Source", "Source Column", "Target Column", "SQL Expression", "SQL Location", "Validation"], *rows(data["traceability"], ("map_group", "source", "source_column", "target_column", "sql_expression", "sql_location", "status"))]), "<h2>13. Final Decision</h2>" + self._table([["Decision", "Result"], ["SQL Generation", final["sql_generation"]], ["Deterministic Validation", final["deterministic_validation"]], ["BA Review Required", "YES" if final["ba_review_required"] else "NO"], ["Reason", final["reason"]]])]
        return "<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>AccelerateX SQL Generation &amp; Validation Report</title><style>:root{font-family:'Segoe UI',system-ui,sans-serif;color:#e8eef4;background:#081019;--ink:#e8eef4;--muted:#8d9aaa;--line:#253544;--glass:rgba(16,28,40,.72);--glass-strong:rgba(20,35,50,.9);--cyan:#58d2dc;--amber:#f3b867;--danger:#ff8b8b}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 12% 10%,#17334a 0,transparent 33%),radial-gradient(circle at 90% 88%,#1c2934 0,transparent 30%),#081019}body:before{content:'';position:fixed;inset:0;pointer-events:none;opacity:.24;background-image:linear-gradient(rgba(130,170,190,.08) 1px,transparent 1px),linear-gradient(90deg,rgba(130,170,190,.08) 1px,transparent 1px);background-size:48px 48px;mask-image:linear-gradient(to bottom,black,transparent 80%)}main{max-width:1280px;margin:auto;padding:34px 42px 70px}header{padding:22px 0 30px;border-bottom:1px solid var(--line)}h1{font-size:clamp(2.4rem,6vw,5.6rem);line-height:.96;margin:12px 0 16px;letter-spacing:-.055em;font-weight:650;color:var(--ink)}h2{font-size:1.55rem;margin:42px 0 10px;color:var(--ink);border-bottom:1px solid var(--line);padding-bottom:10px}.eyebrow{color:var(--cyan);font-size:.7rem;font-weight:700;letter-spacing:.18em;text-transform:uppercase}.panel-kicker{color:var(--cyan);font-size:.7rem;font-weight:700;letter-spacing:.18em}.panel{background:linear-gradient(135deg,rgba(29,48,65,.74),rgba(11,22,32,.74));border:1px solid rgba(123,163,183,.22);border-radius:10px;padding:22px;box-shadow:0 18px 48px rgba(0,0,0,.2);backdrop-filter:blur(16px);margin:16px 0}.metric-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.metric{padding:18px 20px;background:var(--glass);border:1px solid var(--line);border-radius:8px}.metric-label{color:var(--muted);font-size:.75rem}.metric-value{font-size:1.65rem;font-weight:650;margin-top:8px}.muted,.empty{color:var(--muted)}table{width:100%;border-collapse:collapse;background:rgba(16,28,40,.7);margin:12px 0 20px;border:1px solid var(--line);display:block;overflow-x:auto}th,td{border:1px solid var(--line);padding:10px 12px;text-align:left;vertical-align:top;white-space:normal}th{background:rgba(88,210,220,.09);color:var(--cyan);font-size:.74rem;letter-spacing:.05em;text-transform:uppercase}td{color:var(--ink)}pre{background:#050b11;color:#dceef1;border:1px solid var(--line);padding:18px;overflow:auto;border-radius:6px;line-height:1.5}.sql{box-shadow:inset 0 0 30px rgba(88,210,220,.04)}.notice{padding:14px;border-left:4px solid var(--amber);background:rgba(243,184,103,.08)}li{margin:6px 0;color:var(--muted)}@media(max-width:760px){main{padding:24px 16px 48px}h1{font-size:2.7rem}.metric-grid{grid-template-columns:repeat(2,1fr)}th,td{padding:8px;font-size:.8rem}}</style></head><body><main><header><p class='eyebrow'>AccelerateX / SQL generation</p>" + "".join(sections) + "</header></main></body></html>"

    def _render_validator_style(self, data: dict) -> str:
        def rows(mapping, keys):
            return [[item[key] for key in keys] for item in mapping]

        def table(headers, values, compact=False):
            rendered = self._table([headers, *values])
            return rendered.replace("<table>", "<table class='compact-table'>", 1) if compact else rendered

        summary = data["summary"]
        inputs = data["inputs"]
        final = data["final_status"]
        status = summary["overall_status"]
        status_class = "passed" if status == "SUCCESS" else "warning" if status == "WARNING" else "failed"
        action = "Proceed to the testing phase by generating sample synthetic data using the Test Data Forge." if status == "SUCCESS" else "Review the deterministic findings and TODOs before continuing."
        summary_rows = [[key.replace("_", " ").title(), value] for key, value in summary.items()]
        input_rows = [[key.replace("_", " ").title(), value] for key, value in inputs.items()]
        mapping_rows = rows(data["mapping_analysis"], ("map_group", "source", "source_column", "target", "target_column", "transformation", "join_dependency", "status"))
        source_rows = rows(data["source_object_analysis"], ("object", "alias", "select", "join", "where", "transformation", "filter_conditions", "join_participation"))
        fix_rows = rows(data["deterministic_fixes"], ("id", "issue", "action", "location", "impact", "status"))
        finding_rows = rows(data["deterministic_findings"], ("severity", "category", "finding", "evidence", "recommendation"))
        todo_rows = rows(data["todos"], ("id", "category", "description", "source", "impact", "required_action", "owner"))
        validation_rows = [[item["rule"], item["result"], item["details"]] for item in data["validation"]]
        rag_rows = [[item["name"]] for item in data["rag_advisory"]["rules"]]
        llm = data["llm_diagnostic"]
        llm_rows = [["Model", llm["model"]], ["Diagnostic Status", llm["status"]], ["Prompt Purpose", llm["prompt_purpose"]], ["Issues Explained", json.dumps(llm["issues_explained"])], ["Authority", llm["authority"]], ["Explanation & Recommendation", llm["explanation"]]]
        if llm.get("error"):
            llm_rows.append(["Error", llm["error"]])
        trace_rows = rows(data["traceability"], ("map_group", "source", "source_column", "target_column", "sql_expression", "sql_location", "status"))
        source_change_rows = rows(data.get("source_sql_changes", []), ("change_type", "area", "identifier", "source_sql", "generated_sql"))
        trace_table = table(["Map Group", "Source", "Source Column", "Target Column", "SQL Expression", "SQL Location", "Validation"], trace_rows).replace("<table>", "<table class='trace-table'>", 1)
        change_table = "<div class='change-table-wrap'><table class='change-table'><thead><tr><th>Change</th><th>Area</th><th>Identifier</th><th>Existing SQL</th><th>Generated SQL</th></tr></thead><tbody>" + "".join("<tr><td><span class='change-badge change-" + escape(str(item[0]).lower()) + "'>" + escape(str(item[0])) + "</span></td><td>" + escape(str(item[1])) + "</td><td><strong>" + escape(str(item[2])) + "</strong></td><td><code>" + escape(str(item[3])) + "</code></td><td><code>" + escape(str(item[4])) + "</code></td></tr>" for item in source_change_rows) + "</tbody></table></div>" if source_change_rows else "<p class='empty'>No existing source SQL was supplied.</p>"
        metadata = " | ".join(f"<strong>{escape(str(key).replace('_', ' ').title())}:</strong> {escape(str(value))}" for key, value in data["sql_metadata"].items())
        panels = [
            "<section class='panel'><p class='eyebrow'>01 / SUMMARY</p><h2>Deterministic SQL outcome</h2>" + table(["Metric", "Result"], summary_rows, compact=True) + "</section>",
            "<section class='panel'><p class='eyebrow'>02 / INPUT SCOPE</p><h2>Workbook and source context</h2>" + table(["Input", "Value"], input_rows) + "</section>",
            "<section class='panel wide'><p class='eyebrow'>03 / MAPPING ANALYSIS</p><h2>Mapping rows carried into SQL</h2>" + table(["Map Group", "Source", "Source Column", "Target", "Target Column", "Transformation", "Join Dependency", "Status"], mapping_rows) + "</section>",
            "<section class='panel wide'><p class='eyebrow'>04 / SOURCE OBJECTS</p><h2>Objects participating in generation</h2>" + table(["Source Object", "Alias", "SELECT", "JOIN", "WHERE", "Transformation", "Filters", "Join Participation"], source_rows) + "</section>",
            "<section class='panel wide'><p class='eyebrow'>05 / GENERATED SQL</p><div style='display:flex;align-items:center;justify-content:space-between;gap:16px'><h2>Final deterministic SQL</h2><button type='button' style='border:1px solid rgba(88,210,220,.55);border-radius:5px;background:rgba(88,210,220,.1);color:#58d2dc;padding:8px 13px;font:inherit;font-size:.82rem;font-weight:700;cursor:pointer' onclick=\"navigator.clipboard.writeText(document.getElementById('generated-sql').textContent).then(() => { this.textContent = 'Copied'; setTimeout(() => this.textContent = 'Copy SQL', 1500); })\">Copy SQL</button></div><p class='muted'>" + metadata + "</p><pre id='generated-sql' class='sql'>" + escape(data["generated_sql"]) + "</pre></section>",
            "<section class='panel wide'><p class='eyebrow'>06 / DETERMINISTIC FIXES</p><h2>Recorded engine changes</h2>" + table(["#", "Issue Detected", "Action Taken", "Location", "Impact", "Status"], fix_rows) + "</section>",
            "<section class='panel wide'><p class='eyebrow'>07 / DETERMINISTIC FINDINGS</p><h2>Findings and evidence</h2>" + table(["Severity", "Category", "Finding", "Evidence", "Recommendation"], finding_rows) + "</section>",
            "<section class='panel wide'><p class='eyebrow'>08 / TODO / BA REVIEW</p><h2>Items requiring human confirmation</h2>" + (table(["TODO ID", "Category", "Description", "Source", "Impact", "Required Action", "Owner"], todo_rows) if todo_rows else "<p class='success'>No unresolved TODOs identified.</p>") + "</section>",
            "<section class='panel'><p class='eyebrow'>09 / VALIDATION RESULT</p><h2>Deterministic checklist</h2>" + table(["Validation Rule", "Result", "Details"], validation_rows, compact=True) + "</section>",
            "<section class='panel'><p class='eyebrow'>10 / RAG ADVISORY</p><h2>Approved rules consulted</h2>" + table(["Rule"], rag_rows, compact=True) + "</section>",
            "<section class='panel wide'><p class='eyebrow'>11 / LLM DIAGNOSTIC</p><h2>Explanation and recommendation</h2>" + table(["Field", "Value"], llm_rows) + "</section>",
            "<section class='panel wide'><p class='eyebrow'>12 / TRACEABILITY</p><h2>Mapping to generated expression</h2>" + trace_table + "<div class='change-log'><div class='change-log-heading'><div><h3>Existing SQL changes</h3><p class='muted'>Differences between the uploaded source SQL and mapping-driven output.</p></div><span class='change-count'>" + str(len(source_change_rows)) + " changes</span></div>" + change_table + "</div></section>",
        ]
        panels.insert(0, "<style>main{width:100%;max-width:none;padding:clamp(24px,3vw,42px) clamp(18px,3vw,48px) 70px}</style>")
        return "<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>SQL Generation Report | AccelerateX</title><style>:root{font-family:'Segoe UI',system-ui,sans-serif;color:#e8eef4;background:#081019;--ink:#e8eef4;--muted:#8d9aaa;--line:#253544;--cyan:#58d2dc;--amber:#f3b867;--danger:#ff8b8b;--green:#7be0b5}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 12% 10%,#17334a 0,transparent 33%),radial-gradient(circle at 90% 88%,#1c2934 0,transparent 30%),#081019}body:before{content:'';position:fixed;inset:0;pointer-events:none;opacity:.24;background-image:linear-gradient(rgba(130,170,190,.08) 1px,transparent 1px),linear-gradient(90deg,rgba(130,170,190,.08) 1px,transparent 1px);background-size:48px 48px}main{width:min(100%,1440px);margin:0 auto;padding:42px 34px 70px;position:relative}header{padding:14px 0 30px;border-bottom:1px solid var(--line)}.eyebrow{color:var(--cyan);font-size:.7rem;font-weight:700;letter-spacing:.18em}h1{font-size:clamp(2rem,5vw,4.4rem);line-height:1;margin:12px 0 14px;letter-spacing:-.04em}h2{font-size:1.35rem;margin:0 0 10px}h3{font-size:1rem;margin:0 0 8px}.lead,.muted,.empty{color:var(--muted)}.status,.panel{background:linear-gradient(135deg,rgba(29,48,65,.74),rgba(11,22,32,.74));border:1px solid rgba(123,163,183,.22);border-radius:10px;padding:22px;box-shadow:0 18px 48px rgba(0,0,0,.2);backdrop-filter:blur(16px)}.status{margin-top:22px;border-left:4px solid var(--cyan);display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center}.status.failed{border-left-color:var(--danger)}.status.warning{border-left-color:var(--amber)}.status.passed{border-left-color:var(--green)}.status strong{font-size:1.25rem}.success{color:var(--green)}.warning{color:var(--amber)}.error{color:var(--danger)}.advisory-banner{background:linear-gradient(135deg,rgba(88,210,220,.09),rgba(29,48,65,.74));border:1px solid rgba(88,210,220,.25);border-radius:10px;padding:18px 20px;margin-top:18px}.advisory-banner h3{margin:6px 0 0}.report-grid{display:grid;grid-template-columns:1.15fr .85fr;gap:18px;margin-top:18px}.report-grid .wide{grid-column:1/-1}.panel{margin-top:18px}.panel h2{font-size:1.3rem}.panel table{margin-top:16px}table{width:100%;border-collapse:collapse;margin:0;display:block;overflow-x:auto;background:rgba(5,14,23,.34)}.compact-table{display:table;width:100%;min-width:340px;max-width:100%}.trace-table{min-width:0}th,td{border:1px solid var(--line);padding:10px 12px;text-align:left;vertical-align:top;white-space:normal}th{background:rgba(88,210,220,.09);color:var(--cyan);font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;white-space:nowrap}td{color:var(--ink)}pre{background:#050b11;color:#dceef1;border:1px solid var(--line);padding:18px;overflow:auto;border-radius:6px;line-height:1.5}.sql{box-shadow:inset 0 0 30px rgba(88,210,220,.04)}strong{color:var(--cyan)}.change-log{margin-top:24px;padding-top:20px;border-top:1px solid var(--line)}.change-log-heading{display:flex;align-items:end;justify-content:space-between;gap:16px;margin-bottom:12px}.change-log-heading h3{margin:0;font-size:1.05rem}.change-log-heading .muted{margin:5px 0 0;font-size:.82rem}.change-count{color:var(--muted);font-size:.75rem;text-transform:uppercase;letter-spacing:.1em}.change-table-wrap{width:100%;overflow-x:auto}.change-table{display:table;width:max-content;min-width:100%;table-layout:auto}.change-table th,.change-table td{padding:10px 12px}.change-table th:nth-child(1){min-width:112px}.change-table th:nth-child(2){min-width:76px}.change-table th:nth-child(3){min-width:150px}.change-table th:nth-child(4),.change-table th:nth-child(5){min-width:280px}.change-table code{display:block;white-space:pre-wrap;overflow-wrap:anywhere;color:#cfe7eb;font:inherit;line-height:1.45}.change-badge{display:inline-block;padding:4px 7px;border-radius:4px;font-size:.66rem;font-weight:800;letter-spacing:.08em}.change-removed{color:#ffb4b4;background:rgba(255,139,139,.13)}.change-changed{color:#ffd08d;background:rgba(243,184,103,.13)}.change-added{color:#a8f0cf;background:rgba(123,224,181,.13)}.change-unchanged{color:#a9dce1;background:rgba(88,210,220,.1)}@media(max-width:800px){main{padding:32px 20px 54px}.report-grid{display:block}.panel{margin-top:16px}.change-log-heading{align-items:start;flex-direction:column}h1{font-size:3rem}.compact-table{width:100%}.change-table{display:table;min-width:860px}}</style></head><body><main><header><p class='eyebrow'>OPERATIONS / MAPPING VALIDATOR</p><h1>Mapping Validation Report</h1><p class='lead'>Workbook: " + escape(str(inputs.get("mapping_workbook", "Unknown"))) + "</p></header><section class='status " + status_class + "'><strong>SQL GENERATION STATUS - " + escape(status) + "</strong><p>" + escape(str(summary["validation_status"])) + " deterministic validation</p></section><div class='advisory-banner'><p class='eyebrow'>NEXT ACTION</p><h3>" + escape(action) + "</h3></div><div class='report-grid'>" + "".join(panels) + "</div></main></body></html>"

    def write_report(self, report_html: str, output_dir: str, target_table: str) -> str:
        path = Path(output_dir) / "report" / f"{target_table.lower()}_report.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report_html, encoding="utf-8")
        return str(path)

    def write_json(self, report_data: dict, output_dir: str, target_table: str) -> str:
        path = Path(output_dir) / "report" / f"{target_table.lower()}_report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report_data, indent=2, default=str), encoding="utf-8")
        return str(path)
