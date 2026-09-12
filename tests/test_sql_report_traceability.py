from engine.sql_generator.report_generator import ReportGenerator
from engine.sql_generator.sql_generator import SQLGenerator
import pandas as pd


def test_traceability_reports_removed_source_expressions_and_joins(tmp_path):
    source_path = tmp_path / "prty.sql"
    source_path.write_text(
        """SELECT
    CPI.PRTY_SROGT_ID AS s_prty,
    CPI.PRTY_CD AS id_type,
    UPPER(CPI.ID_REF) AS N_CUST,
    PRTY.PRTY_NAME AS prty_name
FROM C_PRTY PRTY
LEFT JOIN (
    SELECT PRTY_SROGT_ID, ID_REF, PRTY_CD
    FROM C_PRTY_ID
    WHERE DATA_SRC = 'EBB'
      AND SOURCE_COUNTRY_CODE = 'VN'
      AND ID_TP_CD = 'N01'
) CPI
    ON PRTY.PRTY_SROGT_ID = CPI.PRTY_SROGT_ID
""",
        encoding="utf-8",
    )
    generated_path = tmp_path / "generated.sql"
    generated_path.write_text("SELECT\n    PRTY.PRTY_NAME AS prty_name\nFROM C_PRTY PRTY\n", encoding="utf-8")

    data = ReportGenerator({}).build_report_data(
        {"mapping_rows": [], "select_columns": ["PRTY.PRTY_NAME AS prty_name"]},
        str(generated_path),
        context={"source_sql_path": str(source_path)},
    )

    changes = data["source_sql_changes"]
    removed = {(item["area"], item["identifier"]) for item in changes if item["change_type"] == "REMOVED"}
    assert {("SELECT", "S_PRTY"), ("SELECT", "ID_TYPE"), ("SELECT", "N_CUST")} <= removed
    assert ("JOIN", "CPI") in removed
    assert "Existing SQL changes" in ReportGenerator({}).generate_report(
        {"mapping_rows": [], "select_columns": ["PRTY.PRTY_NAME AS prty_name"]},
        str(generated_path),
        context={"source_sql_path": str(source_path)},
    )


def test_generation_keeps_only_mapping_aliases_when_source_sql_is_supplied(tmp_path):
    workbook_path = tmp_path / "mapping.xlsx"
    with pd.ExcelWriter(workbook_path) as writer:
        pd.DataFrame([
            {"Map Group ID": "G1", "Target Object Name": "PRTY", "Target Attribute Name": "S_PRTY", "Source Object Name": "PRTY", "Source Attribute Name": "PRTY_SROGT_ID"},
        ]).to_excel(writer, sheet_name="Source to Target", index=False)
        pd.DataFrame(columns=["Rule Name", "Process Type"]).to_excel(writer, sheet_name="DPR", index=False)
        pd.DataFrame([{"Map Group Code": "G1", "Join": "FROM C_PRTY PRTY"}]).to_excel(writer, sheet_name="Map Group Code", index=False)

    source_sql = """SELECT
    CPI.PRTY_SROGT_ID AS S_PRTY,
    CPI.PRTY_CD AS ID_TYPE,
    UPPER(CPI.ID_REF) AS N_CUST
FROM C_PRTY PRTY
LEFT JOIN (SELECT PRTY_SROGT_ID, PRTY_CD, ID_REF FROM C_PRTY_ID) CPI
    ON PRTY.PRTY_SROGT_ID = CPI.PRTY_SROGT_ID
"""
    result = SQLGenerator(str(workbook_path)).generate("PRTY", "G1", str(tmp_path), source_sql)

    assert "AS S_PRTY" in result["sql"].upper()
    assert "AS ID_TYPE" not in result["sql"].upper()
    assert "AS N_CUST" not in result["sql"].upper()
    assert not any("updated to match mapping sheet" in warning for warning in result["warnings"])