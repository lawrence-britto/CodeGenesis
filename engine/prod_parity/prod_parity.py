from dataclasses import dataclass, field
import difflib, re
from engine.sql_generator.source_sql_parser import parse_source_sql

@dataclass
class ParityComparison:
    identical: bool
    added_lines: int
    removed_lines: int
    unified_diff: str
    added_columns: list[str] = field(default_factory=list)
    removed_columns: list[str] = field(default_factory=list)
    added_tables: list[str] = field(default_factory=list)
    removed_tables: list[str] = field(default_factory=list)
    message: str = ""

def compare_sql_text(generated_text: str, prod_text: str) -> ParityComparison:
    diff = list(difflib.unified_diff(prod_text.splitlines(keepends=True), generated_text.splitlines(keepends=True), fromfile="prod sql", tofile="generated sql"))
    added = sum(line.startswith("+") and not line.startswith("+++") for line in diff)
    removed = sum(line.startswith("-") and not line.startswith("---") for line in diff)
    added_columns: list[str] = []
    removed_columns: list[str] = []
    added_tables: list[str] = []
    removed_tables: list[str] = []
    analysis_warning = ""
    try:
        prod, generated = parse_source_sql(prod_text), parse_source_sql(generated_text)
        added_columns = sorted(generated["select_aliases"] - prod["select_aliases"]); removed_columns = sorted(prod["select_aliases"] - generated["select_aliases"])
        table_re = re.compile(r"\b(?:FROM|JOIN)\s+([\w.$]+)", re.I)
        prod_tables = set(table_re.findall(prod["join_text"])); generated_tables = set(table_re.findall(generated["join_text"]))
        added_tables = sorted(generated_tables - prod_tables); removed_tables = sorted(prod_tables - generated_tables)
    except (KeyError, TypeError, ValueError, re.error) as error:
        analysis_warning = f" Structural analysis unavailable: {type(error).__name__}: {error}. Line comparison is still available."
    identical = added == removed == 0
    message = "No differences found - safe to deploy." if identical else f"{added} line(s) added, {removed} line(s) removed vs production. Review before deployment"
    return ParityComparison(identical, added, removed, "".join(diff), added_columns, removed_columns, added_tables, removed_tables, message + analysis_warning)
