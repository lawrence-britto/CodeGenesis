from engine.mapping_validator.mapping_validator import validate_mapping_sheet_file
from engine.mapping_validator.rules import build_rule_manifest, list_secondary_rules, load_secondary_validation_rules
from engine.rag.service import explain_issue


def test_build_rule_manifest_is_generated_from_knowledge_and_filters_selected_rules(tmp_path):
    manifest_path = tmp_path / "rule_manifest.json"
    manifest = build_rule_manifest("mapping", selected_rule_ids={"duplicate_target_mapping"}, output_path=manifest_path)

    assert manifest["module"] == "mapping"
    assert [rule["id"] for rule in manifest["rules"]] == ["duplicate_target_mapping"]
    assert manifest["rules"][0]["title"] == "Duplicate target mapping"
    assert manifest_path.exists()


def test_list_secondary_rules_respects_selected_rule_filter():
    rules = list_secondary_rules("mapping", selected_rule_ids={"duplicate_target_mapping"})

    assert [rule["id"] for rule in rules] == ["duplicate_target_mapping"]
    assert [rule["title"] for rule in rules] == ["Duplicate target mapping"]


def test_selected_markdown_rules_stay_secondary_even_without_executable_checks():
    manifest = build_rule_manifest("mapping", selected_rule_ids={"duplicate_dpr_rule"})

    assert manifest["rules"][0]["id"] == "duplicate_dpr_rule"
    assert manifest["rules"][0]["title"] == "Duplicate DPR Rule"
    assert manifest["rules"][0]["layer"] == "secondary"
    assert manifest["rules"][0]["executable"] is False


def test_load_secondary_validation_rules_respects_manifest_selection():
    rules = load_secondary_validation_rules("mapping", selected_rule_ids={"duplicate_target_mapping"})

    assert [rule.title for rule in rules] == ["Duplicate target mapping"]


def test_validate_mapping_sheet_file_accepts_selected_rule_filter(tmp_path):
    xl_path = tmp_path / "selected_rule_validation.xlsx"
    with open(xl_path, "wb") as handle:
        handle.write(b"stub")

    result = validate_mapping_sheet_file(str(xl_path), {}, selected_rule_ids={"duplicate_target_mapping"})

    assert result.status == "fail"
    assert result.passed is False


def test_explain_issue_uses_selected_secondary_markdown_rules_only():
    result = explain_issue("Authoritative deterministic status: PASS. Findings: none", "mapping", selected_rule_ids={"duplicate_target_mapping"})

    assert [rule["title"] for rule in result["rules"]] == ["Duplicate target mapping"]
