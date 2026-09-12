from app.routers.prod_parity import _universal_advisory_fallback
from engine.universal_service import analyze_files
from engine.validators import detect_language, validate_content


def test_detects_sql_content_with_txt_extension():
    result = detect_language('query.txt', 'SELECT customer_id FROM customers WHERE active = 1')
    assert result['language'] == 'sql'
    assert 'SQL' in result['note']


def test_python_ast_validation_reports_syntax_location():
    result = validate_content('def broken(:\n    pass\n', 'python')
    assert result.valid is False
    assert result.errors[0].code == 'PYTHON_SYNTAX'
    assert result.errors[0].line == 1


def test_sql_formatting_change_is_not_semantic_change():
    result = analyze_files(
        'SELECT a, b FROM users;',
        'SELECT\n    a,\n    b\nFROM users;\n',
        'tested.sql',
        'baseline.sql',
    )
    assert result.text_difference is True
    assert result.semantic_difference is False
    assert result.overall == 'SAFE'


def test_sql_semantic_change_requires_review_without_high_risk_pattern():
    result = analyze_files('SELECT name FROM users;', 'SELECT id FROM users;', 'tested.sql', 'baseline.sql')
    assert result.semantic_difference is True
    assert result.overall == 'WARNING - REVIEW CHANGES'


def test_sql_removed_where_is_high_risk():
    result = analyze_files(
        'SELECT id FROM users;',
        'SELECT id FROM users WHERE active = 1;',
        'tested.sql',
        'baseline.sql',
    )
    assert any(finding.code == 'SQL_WHERE_REMOVED' for finding in result.risk_findings)
    assert result.overall == 'HIGH RISK - REVIEW CHANGES'


def test_sql_added_join_is_high_risk():
    result = analyze_files('SELECT id FROM users JOIN accounts ON accounts.id = users.id;', 'SELECT id FROM users;', 'tested.sql', 'baseline.sql')
    assert any(finding.code == 'SQL_JOIN_ADDED' for finding in result.risk_findings)
    assert result.overall == 'HIGH RISK - REVIEW CHANGES'


def test_sql_join_condition_change_is_high_risk():
    result = analyze_files(
        'SELECT users.id FROM users JOIN accounts ON accounts.user_id = users.id;',
        'SELECT users.id FROM users JOIN accounts ON accounts.id = users.id;',
        'tested.sql',
        'baseline.sql',
    )
    assert any(finding.code == 'SQL_JOIN_CHANGED' for finding in result.risk_findings)
    assert result.overall == 'HIGH RISK - REVIEW CHANGES'


def test_sql_removed_column_gets_result_shape_finding():
    result = analyze_files('SELECT id FROM users;', 'SELECT id, email FROM users;', 'tested.sql', 'baseline.sql')
    assert any(finding.code == 'SQL_COLUMNS_CHANGED' for finding in result.risk_findings)


def test_sql_removed_clause_gets_query_logic_finding():
    result = analyze_files('SELECT id FROM users;', 'SELECT id FROM users ORDER BY id;', 'tested.sql', 'baseline.sql')
    assert any(finding.code == 'SQL_CLAUSES_CHANGED' for finding in result.risk_findings)


def test_yaml_key_order_is_semantically_equivalent():
    result = analyze_files(
        'replicas: 3\nimage: app:v1\n',
        'image: app:v1\nreplicas: 3\n',
        'tested.yaml',
        'baseline.yaml',
    )
    assert result.text_difference is True
    assert result.semantic_difference is False


def test_shell_destructive_command_is_not_executed_but_flagged():
    result = analyze_files('rm -rf /tmp/example\n', 'echo ready\n', 'tested.sh', 'baseline.sh')
    assert any(finding.code == 'SHELL_RM_RF' for finding in result.risk_findings)
    assert result.overall == 'HIGH RISK - REVIEW CHANGES'


def test_canonical_diff_preserves_baseline_to_tested_direction():
    result = analyze_files(
        'SELECT\n    new_value\n    added_value\nFROM source;\n',
        'SELECT\n    old_value\nFROM source;\n',
        'tested.sql',
        'baseline.sql',
    )
    assert result.baseline_filename == 'baseline.sql'
    assert result.tested_filename == 'tested.sql'
    assert [(line['kind'], line['content']) for line in result.diff_lines if line['kind'] != 'context'] == [
        ('removed', '    old_value'),
        ('added', '    new_value'),
        ('added', '    added_value'),
    ]
    assert result.side_by_side[1]['change_type'] == 'modified'
    assert result.side_by_side[2]['change_type'] == 'added'


def test_basic_analysis_does_not_promote_validation_warnings_to_risk_findings():
    result = analyze_files('SELECT * FROM users;\n', 'SELECT id FROM users;\n', 'tested.sql', 'baseline.sql', analysis_level='basic')
    assert result.risk_findings == []


def test_universal_advisory_fallback_explains_semantic_change():
    result = analyze_files(
        'SELECT new_value FROM source;\n',
        'SELECT old_value FROM source;\n',
        'tested.sql',
        'baseline.sql',
        analysis_level='deep',
    )
    explanation = _universal_advisory_fallback(result)
    assert 'adds 1 line(s) and removes 1 line(s)' in explanation
    assert 'semantic difference' in explanation
