from engine.rag import service


def test_explain_issue_pass_result_returns_success_message(monkeypatch):
    rules = [
        {"id": "1", "title": "Required workbook structure", "text": "Pass when workbook contains Source to Target sheet."},
        {"id": "2", "title": "Required mapping columns", "text": "Pass when required columns exist."},
    ]
    monkeypatch.setattr(service, "retrieve_rules", lambda *args, **kwargs: rules)
    monkeypatch.setattr(service, "load_config", lambda: {"llm": {"provider": "ollama", "model": "qwen2.5-coder:7b"}})

    result = service.explain_issue(
        "Authoritative deterministic status: PASS. Findings: none",
        "mapping",
        set(),
    )

    assert result["explanation"] == "Proceed to the SQL Generation module using the validated mapping sheet."
    assert result["error"] == ""
    assert result["rules"]


def test_explain_issue_review_result_returns_ba_review_message(monkeypatch):
    rules = [
        {"id": "1", "title": "Duplicate target mapping", "text": "Pass when a target object and target attribute occur once per map group."},
        {"id": "2", "title": "Active mapping rows", "text": "Conflicting active and inactive versions require analyst review."},
    ]
    monkeypatch.setattr(service, "retrieve_rules", lambda *args, **kwargs: rules)
    monkeypatch.setattr(service, "load_config", lambda: {"llm": {"provider": "ollama", "model": "qwen2.5-coder:7b"}})

    result = service.explain_issue(
        "Authoritative deterministic status: REVIEW. Findings: Duplicate target mapping in Map Group A; conflicting active and inactive rows",
        "mapping",
        set(),
    )

    assert result["explanation"] == "This mapping is under review.\nPlease check with the BA before proceeding to SQL generation."
    assert result["error"] == ""
    assert result["rules"]


def test_explain_issue_sql_pass_result_points_to_testing(monkeypatch):
    monkeypatch.setattr(service, "retrieve_rules", lambda *args, **kwargs: [])

    result = service.explain_issue(
        "Authoritative deterministic status: PASS. Findings: none",
        "sql",
        set(),
    )

    assert result["explanation"] == "Proceed to the testing phase by generating sample synthetic data using the Test Data Forge."
    assert result["error"] == ""


def test_explain_issue_fail_result_returns_corrective_measures(monkeypatch):
    rules = [
        {"id": "1", "title": "Non-empty map group", "text": "Pass when every mapping row has a non-empty Map Group ID."},
        {"id": "2", "title": "Non-empty source attribute", "text": "Pass when each mapping row identifies a source attribute and source attribute ID."},
        {"id": "3", "title": "Consistent target per group", "text": "Pass when all rows in a map group point to one target table."},
    ]
    monkeypatch.setattr(service, "retrieve_rules", lambda *args, **kwargs: rules)
    monkeypatch.setattr(service, "load_config", lambda: {"llm": {"provider": "ollama", "model": "qwen2.5-coder:7b"}})

    result = service.explain_issue(
        "Authoritative deterministic status: FAIL. Findings: 1 row(s) have a blank Map Group ID at Excel row(s) 6; 1 row(s) have a blank Source Attribute Name at Excel row(s) 27; Map Group 'RBC-FD-C_PRTY~PRTY~1' maps to more than one target table - verify this is intentional",
        "mapping",
        set(),
    )

    assert "Proceed to the SQL Generation module" not in result["explanation"]
    assert "Corrective action:" in result["explanation"]
    assert "Map Group ID" in result["explanation"]
    assert result["error"] == ""
