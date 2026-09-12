from engine.sql_generator.sql_generator import SQLGenerator
from engine.sql_generator.sql_syntax_fixer import fix_sql_string
from engine.mapping_validator.mapping_validator import validate_mapping_sheet_file
from engine.mapping_validator.rules import load_secondary_validation_rules
from engine.rag.service import _is_excluded_rule
from make_mock_mapping_sheet import build_workbook
import pandas as pd


def test_secondary_rules_are_loaded_from_knowledge_titles_only():
    rules = load_secondary_validation_rules("mapping")
    titles = {rule.title for rule in rules}
    assert "Duplicate target mapping" in titles
    assert "Duplicate source mapping" in titles
    assert "Duplicate DPR Rule" not in titles
    assert all(rule.id for rule in rules)


def test_secondary_rule_validation_marks_review_but_does_not_override_fail(tmp_path):
    xl_path = tmp_path / "review_validation.xlsx"
    with pd.ExcelWriter(xl_path) as writer:
        pd.DataFrame([
            {"Map Group ID": "G1", "Source Object Name": "SRC1", "Source Object ID": "1", "Source Attribute Name": "A1", "Source Attribute ID": "10", "Target Object Name": "TGT1", "Target Attribute Name": "C1"},
            {"Map Group ID": "G1", "Source Object Name": "SRC1", "Source Object ID": "1", "Source Attribute Name": "A1", "Source Attribute ID": "10", "Target Object Name": "TGT1", "Target Attribute Name": "C1"},
        ]).to_excel(writer, sheet_name="Source to Target", index=False)
        pd.DataFrame([{"Rule Name": "Approved Rule", "Process Type": "Transform"}]).to_excel(writer, sheet_name="DPR", index=False)
        pd.DataFrame([{"Map Group Code": "G1", "Join": "FROM SRC1"}]).to_excel(writer, sheet_name="Map Group Code", index=False)

    review_result = validate_mapping_sheet_file(str(xl_path), {})
    assert review_result.status == "review"
    assert review_result.passed is True
    assert any(issue.severity == "review" for issue in review_result.issues)

    with pd.ExcelWriter(tmp_path / "fail_override.xlsx") as writer:
        pd.DataFrame([
            {"Map Group ID": "G1", "Source Object Name": "SRC1", "Source Object ID": "1", "Source Attribute Name": "A1", "Source Attribute ID": "10", "Target Object Name": "TGT1", "Target Attribute Name": ""},
        ]).to_excel(writer, sheet_name="Source to Target", index=False)
        pd.DataFrame([{"Rule Name": "Approved Rule", "Process Type": "Transform"}]).to_excel(writer, sheet_name="DPR", index=False)
        pd.DataFrame([{"Map Group Code": "G1", "Join": "FROM SRC1"}]).to_excel(writer, sheet_name="Map Group Code", index=False)

    fail_result = validate_mapping_sheet_file(str(tmp_path / "fail_override.xlsx"), {})
    assert fail_result.status == "fail"
    assert fail_result.passed is False


def test_sql_generator_rejects_malformed_join_and_uses_aliases(tmp_path):
    excel_path = tmp_path / "sql_mapping_sheet.xlsx"
    build_workbook(str(excel_path))

    result = SQLGenerator(str(excel_path)).generate(
        "PRTY_ALT",
        "RBC-FD-C_PRTY~PRTY~1",
        str(tmp_path),
    )
    sql = result["sql"]

    assert "version 1.1 start" not in sql.lower()
    assert "FROM\nFROM" not in sql
    assert "SELECT *" not in sql.upper()
    assert "C_ACCT" not in sql
    assert "cprty.PRTY_SROGT_ID AS prty_attr_10" in sql
    assert sql.count("FROM") >= 1


def test_sql_generator_repairs_missing_from_in_approved_join(tmp_path):
    excel_path = tmp_path / "sql_mapping_sheet.xlsx"
    build_workbook(str(excel_path))

    join = SQLGenerator._enrich_join(
        "FROM (SELECT * C_PRTY WHERE DATA_SRC = 'EBB') PRTY",
        {"C_PRTY"},
    )

    assert "FROM (SELECT * FROM C_PRTY" in join
    assert "TODO: add approved JOIN for C_PRTY" not in join


def test_sql_syntax_fixer_normalizes_join_spacing_empty_strings_and_layout():
    sql = '''SELECT *
FROM (select *FROM C_ACCT where DATA_SRC = 'EBB' and SOURCE_COUNTRY_CODE = 'VN') cacct
LEFT JOIN (select *FROM C_PRTY_ID where DATA_SRC = 'EBB') core_pid
on trim(cacct.prty_srogt_id) = trim(core_pid.PRTY_SROGT_ID) and core_pid.prty_srogt_id <> "'''

    fixed, fixes = fix_sql_string(sql)

    assert "    SELECT *\n    FROM C_ACCT" in fixed
    assert "core_pid.prty_srogt_id <> ''" in fixed
    assert "LEFT JOIN (" in fixed
    assert "    ON trim(cacct.prty_srogt_id) = trim(core_pid.PRTY_SROGT_ID)" in fixed
    assert "   AND core_pid.prty_srogt_id <> ''" in fixed
    assert "normalized SELECT/FROM spacing" in fixes
    assert "normalized empty-string comparisons" in fixes
    assert "standardized JOIN formatting" in fixes


def test_secondary_rule_validation_uses_knowledge_titles_only():
    rules = load_secondary_validation_rules("mapping")
    assert all("Duplicate DPR Rule" not in rule.title for rule in rules)
    assert any(rule.title == "Duplicate source mapping" for rule in rules)
    assert any(rule.title == "Duplicate target mapping" for rule in rules)


def test_unique_dpr_rules_are_source_driven_for_card_currency(tmp_path):
    excel_path = tmp_path / "sql_mapping_sheet.xlsx"
    build_workbook(str(excel_path))

    dpr = pd.read_excel(excel_path, sheet_name="DPR", dtype=str).fillna("")
    assert (dpr["Rule Name"].astype(str).str.contains("C_CARD.ACCT_CURY_CD", case=False)).any()

    result = SQLGenerator(str(excel_path)).generate(
        "CRD",
        "RBC-FD-C_CARD-CRD-1",
        str(tmp_path),
    )
    sql = result["sql"]

    assert "UPPER(C_CARD.ACCT_CURY_CD) AS crd_attr_20" in sql
    assert "UPPER(TRIM(C_CARD.ACCT_CURY_CD))" not in sql
